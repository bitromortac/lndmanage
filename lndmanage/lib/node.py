import asyncio
import binascii
import codecs
from collections import OrderedDict, defaultdict
import datetime
import os
import time
from typing import List, TYPE_CHECKING, Optional, Dict

import grpc
from grpc._channel import _Rendezvous
from grpc._channel import _InactiveRpcError
from google.protobuf.json_format import MessageToDict

import lndmanage.grpc_compiled.lightning_pb2 as lnd
import lndmanage.grpc_compiled.lightning_pb2_grpc as lndrpc
import lndmanage.grpc_compiled.router_pb2 as lndrouter
import lndmanage.grpc_compiled.router_pb2_grpc as lndrouterrpc
import lndmanage.grpc_compiled.walletkit_pb2 as lndwalletkit
import lndmanage.grpc_compiled.walletkit_pb2_grpc as lndwalletkitrpc

from lndmanage.lib.network import Network
from lndmanage.lib.exceptions import PaymentTimeOut, NoRoute, OurNodeFailure
from lndmanage.lib import exceptions
from lndmanage.lib.ln_utilities import (
    extract_short_channel_id_from_string,
    convert_short_channel_id_to_channel_id,
    convert_channel_id_to_short_channel_id,
    local_balance_to_unbalancedness
)
from lndmanage.lib.data_types import UTXO, AddressType
from lndmanage.lib.user import yes_no_question
from lndmanage.lib.utilities import convert_dictionary_number_strings_to_ints
from lndmanage import settings

if TYPE_CHECKING:
    from lndmanage.lib.routing import Route

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

NUM_MAX_FORWARDING_EVENTS = 100000
OPEN_EXPIRY_TIME_MINUTES = 8


class LndNode:
    """Implements a synchronous/asynchronous interface to an lnd node."""
    # rpcs
    _routerrpc: lndrouterrpc.RouterStub
    _rpc: lndrpc.LightningStub
    _walletrpc: lndwalletkitrpc.WalletKitStub
    _async_rpc: lndrpc.LightningStub
    _async_routerrpc: lndrouterrpc.RouterStub
    _async_channel: grpc.aio.Channel
    _sync_channel: grpc.Channel

    # attributes (TODO: clean up)
    alias: str
    pub_key: str
    total_capacity: int = 0
    total_local_balance: int = 0
    total_remote_balance: int = 0
    total_channels: int
    num_active_channels: int
    num_peers: int
    total_satoshis_received: int = 0
    total_satoshis_sent: int = 0
    total_private_channels: int = 0
    total_active_channels: int = 0
    blockheight: int

    def __init__(self, config_file: Optional[str] = None,
                 lnd_home: Optional[str] = None,
                 lnd_host: Optional[str] = None, regtest=False):
        """
        :param config_file: path to the config file
        :param lnd_home: path to lnd home folder
        :param lnd_host: lnd host of format "127.0.0.1:9735"
        :param regtest: if the node is representing a regtest node
        """
        if config_file:
            self.config_file = config_file
            self.config = settings.read_config(self.config_file)
        else:
            self.config_file = None
            self.config = None
        self.lnd_home = lnd_home
        self.lnd_host = lnd_host
        self.regtest = regtest

        # configure lndmanage home: (TODO: separate into config)
        # if no lnd_home is given, then use the paths from the config,
        # else override them with default file paths in lnd_home
        if self.lnd_home is not None:
            self.cert_file_path = os.path.join(self.lnd_home, 'tls.cert')
            bitcoin_network = 'regtest' if self.regtest else 'mainnet'
            self.macaroon_file_path = os.path.join(
                self.lnd_home, 'data/chain/bitcoin/',
                bitcoin_network, 'admin.macaroon')
            if self.lnd_host is None:
                raise ValueError('if lnd_home is given, lnd_host must be given')
        else:
            self.cert_file_path = os.path.expanduser(
                self.config['network']['tls_cert_file']
            )
            self.macaroon_file_path = os.path.expanduser(
                self.config['network']['admin_macaroon_file']
            )
            self.lnd_host = self.config['network']['lnd_grpc_host']

    def get_rpc_credentials(self) -> grpc.ChannelCredentials:
        # read the tls certificate
        cert = None
        try:
            with open(self.cert_file_path, 'rb') as f:
                cert = f.read()
        except FileNotFoundError:
            logger.error("tls.cert not found, please configure %s.",
                         self.config_file)
            exit(1)

        # read the macaroon
        try:
            with open(self.macaroon_file_path, 'rb') as f:
                macaroon_bytes = f.read()
                macaroon = codecs.encode(macaroon_bytes, 'hex')
        except FileNotFoundError:
            logger.error("admin.macaroon not found, please configure %s.",
                         self.config_file)
            exit(1)

        def metadata_callback(context, callback):
            callback([('macaroon', macaroon)], None)

        cert_creds = grpc.ssl_channel_credentials(cert)
        auth_creds = grpc.metadata_call_credentials(metadata_callback)

        return grpc.composite_channel_credentials(cert_creds, auth_creds)

    async def connect_async_rpcs(self):
        # This needs to be run within an async context, the loop is being used in the
        # rpc connections.
        logger.debug("Connecting async rpcs.")

        self._async_channel = grpc.aio.secure_channel(
            self.lnd_host, self.get_rpc_credentials(),
            options=[('grpc.max_receive_message_length', 50 * 1024 * 1024)])

        # establish async connections to rpc servers
        self._async_rpc = lndrpc.LightningStub(self._async_channel)
        self._async_routerrpc = lndrouterrpc.RouterStub(self._async_channel)

    def connect_sync_rpcs(self):
        self._sync_channel = grpc.secure_channel(
            self.lnd_host, self.get_rpc_credentials(),
            options=[('grpc.max_receive_message_length', 50 * 1024 * 1024)])

        # establish connections to rpc servers
        self._rpc = lndrpc.LightningStub(self._sync_channel)
        self._routerrpc = lndrouterrpc.RouterStub(self._sync_channel)
        self._walletrpc = lndwalletkitrpc.WalletKitStub(self._sync_channel)

    async def start(self):
        logger.debug("Node interface starting.")

        # connect rpcs
        self.connect_sync_rpcs()
        await self.connect_async_rpcs()

        # init attributes that depend on rpc interaction
        self.set_info()
        self.network = Network(self)
        self.update_blockheight()
        self.set_channel_summary()

    async def stop(self):
        logger.debug("Disconnecting rpcs.")

        self._sync_channel.close()
        await self._async_channel.close()

        # wait a bit to close all transports
        await asyncio.sleep(0.01)

    async def __aenter__(self):
        await self.start()

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()

    def update_blockheight(self):
        info = self._rpc.GetInfo(lnd.GetInfoRequest())
        self.blockheight = int(info.block_height)

    def get_channel_info(self, channel_id):
        channel = self._rpc.GetChanInfo(
            lnd.ChanInfoRequest(chan_id=channel_id))
        channel_dict = MessageToDict(
            channel, including_default_value_fields=True)
        channel_dict = convert_dictionary_number_strings_to_ints(channel_dict)
        return channel_dict

    @staticmethod
    def lnd_hops(hops) -> List[lnd.Hop]:
        return [lnd.Hop(**hop) for hop in hops]

    def _to_lnd_route(self, route: 'Route') -> lnd.Route:
        """
        Converts a cleartext route to an lnd route.
        """
        hops = self.lnd_hops(route.hops)
        lnd_route = lnd.Route(
            total_time_lock=route.total_time_lock,
            total_fees=route.total_fee_msat // 1000,
            total_amt=route.total_amt_msat // 1000,
            hops=hops,
            total_fees_msat=route.total_fee_msat,
            total_amt_msat=route.total_amt_msat
        )
        return lnd_route

    def get_invoice(self, amt_msat: int, memo: str) -> lnd.Invoice:
        """
        Creates a new invoice with amt_msat and memo.

        :param amt_msat: int
        :param memo: str
        :return: Hash of invoice preimage.
        """
        invoice = self._rpc.AddInvoice(lnd.Invoice(
            value=amt_msat // 1000, memo=memo))
        return invoice

    def get_rebalance_invoice(self, memo) -> lnd.Invoice:
        """
        Creates a zero amount invoice and gives back it's hash.

        :param memo: Comment for the invoice.
        :return: Hash of the invoice preimage.
        """
        invoice = self._rpc.AddInvoice(lnd.Invoice(value=0, memo=memo))
        return invoice

    def send_to_route(self, route: lnd.Route, payment_hash: bytes):
        """Takes a route and sends to it."""

        request = lndrouter.SendToRouteRequest(
            route=route,
            payment_hash=payment_hash,
        )

        try:
            # timeout after 5 minutes
            payment = self._routerrpc.SendToRouteV2(request, timeout=5 * 60)
        except _Rendezvous:
            raise PaymentTimeOut
        except _InactiveRpcError:
            raise PaymentTimeOut
        if payment.HasField('failure'):
            failure = payment.failure  # type: lnd.Failure.FailureCode
            logger.debug(f"Routing failure: {failure}")
            if failure.failure_source_index == 0:
                raise OurNodeFailure("Not enough funds?")
            if failure.code == 12:
                raise exceptions.FeeInsufficient(payment)
            elif failure.code == 13:
                raise exceptions.IncorrectCLTVExpiry(payment)
            elif failure.code == 14:
                raise exceptions.ChannelDisabled(payment)
            elif failure.code == 15:
                raise exceptions.TemporaryChannelFailure(payment)
            elif failure.code == 18:
                raise exceptions.UnknownNextPeer(payment)
            elif failure.code == 19:
                raise exceptions.TemporaryNodeFailure(payment)
            else:
                logger.info(f"Unknown error: code: {failure.code}")
                raise exceptions.TemporaryChannelFailure(payment)

        return payment

    def build_route(self, amt_msat: int, outgoing_chan_id: int,
        hop_pubkeys: List[str], payment_addr: bytes) -> lnd.Route:
        """ Queries the routerrpc endpoint to build a route."""

        final_cltv_delta = 144

        # Convert hop_pubkeys to List[bytes]
        hop_pubkeys = [bytes.fromhex(n) for n in hop_pubkeys]

        request = lndrouter.BuildRouteRequest(
            amt_msat = amt_msat,
            final_cltv_delta = final_cltv_delta,
            outgoing_chan_id = outgoing_chan_id,
            hop_pubkeys = hop_pubkeys,
            payment_addr = payment_addr,
        )

        return self._routerrpc.BuildRoute(request, timeout=5 * 60).route

    def get_raw_network_graph(self):
        try:
            graph = self._rpc.DescribeGraph(lnd.ChannelGraphRequest())
            return graph
        except _Rendezvous:
            logger.error(
                "Problem connecting to lnd. "
                "Either %s is not configured correctly or lnd is not running.",
                self.config_file)
            exit(1)

    def get_raw_info(self):
        """
        Returns specific information about this node.

        :return: node information
        """
        return self._rpc.GetInfo(lnd.GetInfoRequest())

    def set_info(self):
        """
        Fetches information about this node and computes total capacity,
        local and remote total balance, how many satoshis were sent and
        received, and some networking peer stats.
        """

        raw_info = self.get_raw_info()
        self.pub_key = raw_info.identity_pubkey
        self.alias = raw_info.alias
        self.num_active_channels = raw_info.num_active_channels
        self.num_peers = raw_info.num_peers

    def set_channel_summary(self):
        # TODO: remove the following code and implement an advanced status
        all_channels = self.get_open_channels(
            active_only=False, public_only=False)
        self.total_channels = len(all_channels)

        for k, c in all_channels.items():
            self.total_capacity += c['capacity']
            self.total_local_balance += c['local_balance']
            self.total_remote_balance += c['remote_balance']
            self.total_satoshis_received += c['total_satoshis_received']
            self.total_satoshis_sent += c['total_satoshis_sent']
            if c['active']:
                self.total_active_channels += 1
            if c['private']:
                self.total_private_channels += 1

    def get_open_channels(self, active_only=False, public_only=False) \
            -> Dict[int, Dict]:
        """
        Fetches information (fee settings of the counterparty, channel
        capacity, balancedness) about this node's open channels and saves
        it into the channels dict attribute.

        :param active_only: only take active channels into
                            account (off by default)
        :type active_only: bool
        :param public_only: only take public channels into
                            account (off by default)
        :type public_only: bool

        :return: dict of channels sorted by remote pubkey
        :rtype: OrderedDict

        """
        raw_channels = self._rpc.ListChannels(lnd.ListChannelsRequest(
            active_only=active_only, public_only=public_only))
        try:
            channels_data = raw_channels.ListFields()[0][1]
        except IndexError:
            # If there are no channels, return.
            return OrderedDict({})

        channels = OrderedDict()

        for c in channels_data:
            # calculate age from blockheight
            blockheight, _, _ = convert_channel_id_to_short_channel_id(
                c.chan_id)
            age_days = (self.blockheight - blockheight) * 10 / (60 * 24)
            try:
                sent_received_per_week = int(
                    (c.total_satoshis_sent +
                     c.total_satoshis_received) / (age_days / 7))
            except ZeroDivisionError:
                # age could be zero right after channel becomes pending
                sent_received_per_week = 0

            # determine policy:
            try:
                edge_info = self.network.edges[c.chan_id]
                # interested in node2
                policies = edge_info['policies']
                if edge_info['node1_pub'] == self.pub_key:
                    policy_peer = policies[edge_info['node2_pub'] > edge_info['node1_pub']]
                    policy_local = policies[edge_info['node1_pub'] > edge_info['node2_pub']]
                else:  # interested in node1
                    policy_peer = policies[edge_info['node1_pub'] > edge_info['node2_pub']]
                    policy_local = policies[edge_info['node2_pub'] > edge_info['node1_pub']]
            except KeyError:
                # if channel is unknown in describegraph
                # we need to set the fees to some error value
                policy_peer = {
                    'fee_base_msat': float(-999),
                    'fee_rate_milli_msat': float(999)
                }
                policy_local = {
                    'fee_base_msat': float(-999),
                    'fee_rate_milli_msat': float(999)
                }

            # calculate last update (days ago)
            def convert_to_days_ago(timestamp):
                return (time.time() - timestamp) / (60 * 60 * 24)
            try:
                last_update = convert_to_days_ago(
                    self.network.edges[c.chan_id]['last_update'])
                last_update_local = convert_to_days_ago(
                    policy_local['last_update'])
                last_update_peer = convert_to_days_ago(
                    policy_peer['last_update'])
            except (TypeError, KeyError):
                last_update = float('nan')
                last_update_peer = float('nan')
                last_update_local = float('nan')

            # define unbalancedness |ub| large means very unbalanced
            channel_unbalancedness, our_commit_fee = \
                local_balance_to_unbalancedness(
                    c.local_balance, c.capacity, c.commit_fee, c.initiator)
            try:
                uptime_lifetime_ratio = c.uptime / c.lifetime
            except ZeroDivisionError:
                uptime_lifetime_ratio = 0

            channels[c.chan_id] = {
                'active': c.active,
                'age': age_days,
                'alias': self.network.node_alias(c.remote_pubkey),
                'amt_to_balanced': int(
                    channel_unbalancedness * c.capacity / 2 - our_commit_fee),
                'capacity': c.capacity,
                'chan_id': c.chan_id,
                'channel_point': c.channel_point,
                'commit_fee': c.commit_fee,
                'fee_per_kw': c.fee_per_kw,
                'peer_base_fee': policy_peer['fee_base_msat'],
                'peer_fee_rate': policy_peer['fee_rate_milli_msat'],
                'local_base_fee': policy_local['fee_base_msat'],
                'local_fee_rate': policy_local['fee_rate_milli_msat'],
                'local_chan_reserve_sat': c.local_chan_reserve_sat,
                'remote_chan_reserve_sat': c.remote_chan_reserve_sat,
                'initiator': c.initiator,
                'last_update': last_update,
                'last_update_local': last_update_local,
                'last_update_peer': last_update_peer,
                'local_balance': c.local_balance,
                'num_updates': c.num_updates,
                'private': c.private,
                'remote_balance': c.remote_balance,
                'remote_pubkey': c.remote_pubkey,
                'sent_received_per_week': sent_received_per_week,
                'total_satoshis_sent': c.total_satoshis_sent,
                'total_satoshis_received': c.total_satoshis_received,
                'unbalancedness': channel_unbalancedness,
                'uptime': c.uptime,
                'lifetime': c.lifetime,
                'uptime_lifetime_ratio': uptime_lifetime_ratio,
            }
        sorted_dict = OrderedDict(
            sorted(channels.items(), key=lambda x: x[1]['alias']))
        return sorted_dict

    def channel_id_to_node_id(self, open_only=False) -> Dict[int, str]:
        channel_id_to_node_id = {}
        closed_channels = self.get_closed_channels()
        open_channels = self.get_open_channels()
        for cid, c in open_channels.items():
            channel_id_to_node_id[cid] = c['remote_pubkey']
        if not open_only:
            for cid, c in closed_channels.items():
                channel_id_to_node_id[cid] = c['remote_pubkey']
        return channel_id_to_node_id

    def node_id_to_channel_ids(self, open_only=False) -> Dict[str, List[int]]:
        node_channels_mapping = defaultdict(list)
        for cid, nid in self.channel_id_to_node_id(open_only=open_only).items():
            node_channels_mapping[nid].append(cid)
        return node_channels_mapping

    def get_inactive_channels(self):
        """
        Returns all inactive channels.
        :return: dict of channels
        """
        channels = self.get_open_channels(public_only=False, active_only=False)
        return {k: c for k, c in channels.items() if not c['active']}

    def get_all_channels(self, excluded_channels: List[int] = None):
        """
        Returns all active and inactive channels.

        :return: dict of channels
        """
        channels = self.get_open_channels(public_only=False, active_only=False)
        return channels

    def get_unbalanced_channels(self, unbalancedness_greater_than=0.0, excluded_channels: List[int] = None, public_only=True, active_only=True):
        """
        Gets all channels which have an absolute unbalancedness
        (-1...1, -1 for outbound unbalanced, 1 for inbound unbalanced)
        larger than unbalancedness_greater_than.

        :param unbalancedness_greater_than: unbalancedness interval, default returns all channels
        :return: all channels which are more unbalanced than the specified interval
        """
        self.public_active_channels = \
            self.get_open_channels(public_only=public_only, active_only=active_only)
        channels = {
            k: c for k, c in self.public_active_channels.items()
            if abs(c['unbalancedness']) >= unbalancedness_greater_than
        }
        channels = {k: v for k, v in channels.items() if k not in (excluded_channels if excluded_channels else [])}
        return channels

    def get_channel_fee_policies(self):
        """
        Gets the node's channel fee policies for every open channel.
        :return: dict
        """
        feereport = self._rpc.FeeReport(lnd.FeeReportRequest())
        channels = {}
        for fee in feereport.channel_fees:
            channels[fee.channel_point] = {
                'base_fee_msat': fee.base_fee_msat,
                'fee_per_mil': fee.fee_per_mil,
                'fee_rate': fee.fee_rate,
            }
        return channels

    def set_channel_fee_policies(self, channels: dict):
        """
        Sets the node's channel fee policy for every channel.
        :param channels: channel point -> fee policy
        """

        for channel_point, channel_fee_policy in channels.items():
            funding_txid, output_index = channel_point.split(':')
            output_index = int(output_index)

            channel_point = lnd.ChannelPoint(
                funding_txid_str=funding_txid, output_index=output_index)

            update_request = lnd.PolicyUpdateRequest(
                chan_point=channel_point,
                base_fee_msat=channel_fee_policy['base_fee_msat'],
                fee_rate=channel_fee_policy['fee_rate'],
                time_lock_delta=channel_fee_policy['cltv'],
            )
            self._rpc.UpdateChannelPolicy(request=update_request)

    @staticmethod
    def timestamp_from_now(offset_days=0):
        """
        Determines the Unix timestamp from offset_days ago.

        :param offset_days: int
        :return: int, Unix timestamp
        """
        now = datetime.datetime.now()
        then = now - datetime.timedelta(days=offset_days)
        then = time.mktime(then.timetuple())
        return int(then)

    def get_forwarding_events(self, offset_days=300):
        """
        Fetches all forwarding events between now and offset_days ago.

        :param offset_days: int
        :return: lnd fowarding events
        """
        now = self.timestamp_from_now()
        then = self.timestamp_from_now(offset_days)

        forwardings = self._rpc.ForwardingHistory(lnd.ForwardingHistoryRequest(
            start_time=then,
            end_time=now,
            num_max_events=NUM_MAX_FORWARDING_EVENTS))

        events = [{
            'timestamp': f.timestamp,
            'chan_id_in': f.chan_id_in,
            'chan_id_out': f.chan_id_out,
            'amt_in': f.amt_in,
            'amt_in_msat': f.amt_in_msat,
            'amt_out': f.amt_out,
            'amt_out_msat': f.amt_out_msat,
            'fee_msat': f.fee_msat,
            'effective_fee': f.fee_msat / f.amt_in_msat
        } for f in forwardings.forwarding_events]

        return events

    def get_closed_channels(self):
        """
        Fetches all closed channels.

        :return: dict, channel list
        """
        request = lnd.ClosedChannelsRequest()
        closed_channels = self._rpc.ClosedChannels(request)
        closed_channels_dict = {}
        for c in closed_channels.channels:
            closed_channels_dict[c.chan_id] = {
                'channel_point': c.channel_point,
                'chain_hash': c.chain_hash,
                'closing_tx_hash': c.closing_tx_hash,
                'remote_pubkey': c.remote_pubkey,
                'capacity': c.capacity,
                'close_height': c.close_height,
                'settled_balance': c.settled_balance,
                'time_locked_balance': c.time_locked_balance,
                'close_type': c.close_type,
            }
        return closed_channels_dict

    @staticmethod
    def handle_payment_error(payment_error):
        """
        Handles payment errors and determines the failed channel.

        :param payment_error:
        :return: int, channel_id of the failed channel.
        """
        if "TemporaryChannelFailure" in payment_error:
            logger.error("   Encountered temporary channel failure.")
            short_channel_groups = extract_short_channel_id_from_string(payment_error)
            channel_id = convert_short_channel_id_to_channel_id(*short_channel_groups)
            return channel_id

    def queryroute_external(self, source_pubkey, target_pubkey, amt_msat,
                            ignored_nodes=(), ignored_channels={},
                            use_mc=False):
        """
        Queries the lnd node for a route.

        Channels and nodes can be ignored if they failed before.

        :param source_pubkey: source node public key
        :type source_pubkey: str
        :param target_pubkey: target node public key
        :type target_pubkey: str
        :param amt_msat: amount to send in msat
        :type amt_msat: int
        :param ignored_nodes: ignored node pubilc keys for the route
        :type ignored_nodes: list[str]
        :param ignored_channels: ignored channel directions for the route
        :type ignored_channels: dict
        :param use_mc: true if mission control should be used to blacklist
                       channels
        :type use_mc: bool
        :return: route expressed in terms of short channel ids
        :rtype: list[int]
        """
        amt_sat = amt_msat // 1000

        # put safety margin when using mc based routing
        # reason is that routes will not be diverse when sending with a larger
        # amount later on due to fees
        # the fees for the route are somewhat accounted for by the margin
        if use_mc:
            amt_sat = int(amt_sat * 1.02)

        # have a safety max fee in sat
        max_fee = 10000

        # convert ignored nodes to api format
        if ignored_nodes:
            ignored_nodes_api = [bytes.fromhex(n) for n in ignored_nodes]
        else:
            ignored_nodes_api = []

        # convert ignored channels to api format
        if ignored_channels:
            ignored_channels_api = []
            for c, cv in ignored_channels.items():
                direction_reverse = cv['source'] > cv['target']
                ignored_channels_api.append(
                    lnd.EdgeLocator(channel_id=c,
                                    direction_reverse=direction_reverse))
        else:
            ignored_channels_api = []

        logger.debug(f"Ignored for queryroutes: channels: "
                     f"{ignored_channels_api}, nodes: {ignored_nodes_api}")

        request = lnd.QueryRoutesRequest(
            pub_key=target_pubkey,
            amt=amt_sat,
            final_cltv_delta=0,
            fee_limit=lnd.FeeLimit(fixed=max_fee),
            ignored_nodes=ignored_nodes_api,
            ignored_edges=ignored_channels_api,
            source_pub_key=source_pubkey,
            use_mission_control=use_mc,
        )
        try:
            response = self._rpc.QueryRoutes(request)
        except Exception as e:
            if "unable to find a path" in e.details():
                raise NoRoute
            else:
                raise e

        # We give back only one route, as multiple routes will be deprecated
        channel_route = [h.chan_id for h in response.routes[0].hops]

        return channel_route

    def get_node_info(self, pub_key):
        """
        Retrieves information on a node with a specific pub key.

        :param pub_key: node public key
        :type pub_key: str
        :return: node information including all channels
        :rtype: dict
        """
        request = lnd.NodeInfoRequest(pub_key=pub_key, include_channels=True)
        try:
            response = self._rpc.GetNodeInfo(request)
        except _Rendezvous as e:
            if e.details() == "unable to find node":
                logger.info(
                    "LND node has no information about node with pub key %s.",
                    pub_key)
            raise KeyError

        node_info = {
            'alias': response.node.alias,
            'color': response.node.color,
            'channels': response.channels,
            'last_update': response.node.last_update,
            'pub_key': pub_key,
            'num_channels': int(response.num_channels),
            'total_capacity': int(response.total_capacity),  # sat
        }

        addresses = [address.addr for address in response.node.addresses]
        node_info['addresses'] = addresses

        return node_info

    def get_utxos(self) -> List[UTXO]:
        response = self._walletrpc.ListUnspent(
            lndwalletkit.ListUnspentRequest(
                min_confs=1,
                max_confs=100000
            ))
        return [UTXO(
            str(u.outpoint.txid_str),
            int(u.outpoint.output_index),
            int(u.amount_sat),
            AddressType(u.address_type)
        ) for u in response.utxos]

    def print_status(self):
        logger.info("-------- Node status --------")
        if self.total_capacity == 0:
            balancedness_local = 0
            balancedness_remote = 0
        else:
            balancedness_local = self.total_local_balance / self.total_capacity
            balancedness_remote = self.total_remote_balance / self.total_capacity
        logger.info(f"alias: {self.alias}")
        logger.info(f"pub key: {self.pub_key}")
        logger.info(f"blockheight: {self.blockheight}")
        logger.info(f"peers: {self.num_peers}")
        logger.info(f"channels: {self.total_channels}")
        logger.info(f"active channels: {self.total_active_channels}")
        logger.info(f"private channels: {self.total_private_channels}")
        logger.info(f"capacity: {self.total_capacity}")
        logger.info(f"balancedness: l:{balancedness_local:.2%} r:{balancedness_remote:.2%}")
        logger.info(f"total satoshis received (current channels): {self.total_satoshis_received}")
        logger.info(f"total satoshis sent (current channels): {self.total_satoshis_sent}")

    def open_channels(self, pubkeys: List[bytes],
                      amounts_sat: List[int],
                      sat_per_vbyte: int,
                      private=False, test=False):
        channels = []

        logger.info(f">>> Opening channels at {sat_per_vbyte} sat per vbyte:")
        for amount, pubkey in zip(amounts_sat, pubkeys):
            logger.info(f"    {pubkey.hex()}: {amount} sat")
            channels.append(lnd.BatchOpenChannel(
                node_pubkey=pubkey,
                local_funding_amount=amount,
                push_sat=0,
                private=private,
            ))

        logger.info("\n>>> WARNING: This feature is new, use at your own risk. "
                    "Please check the above output carefully.\n")
        logger.info("\n>>> Do you want to open the channel(s) (y/n)?")
        if not test:
            if not yes_no_question('no'):
                return

        request = lnd.BatchOpenChannelRequest(
            channels=channels,
            sat_per_vbyte=sat_per_vbyte,
            label='lndmanage: batch open',
        )
        response = self._rpc.BatchOpenChannel(request)
        logger.info(f">>> Pending channels: {len(response.pending_channels)}")

    def _connect_nodes(self, pubkeys: List[str]) -> List[str]:
        """
        Raises ConnectionRefusedError.
        """
        succeeded_nodes = []
        logger.info(">>> Checking node pubkeys and address information.")
        for pubkey in pubkeys:
            if len(pubkey) != 66:
                raise ValueError(f"pubkey of unknown format {pubkey}")
            info = self.get_node_info(pubkey)
            if not info['addresses']:
                raise ConnectionRefusedError(f"Could not find connection address for {pubkey}.")
        logger.info(">>> Connecting to channel peer candidates.")
        for pubkey in pubkeys:
            info = self.get_node_info(pubkey)
            for address in info['addresses']:
                logger.info(f"    trying to connect to {pubkey}@{address}")
                try:
                    self._rpc.ConnectPeer(
                        lnd.ConnectPeerRequest(
                            addr=lnd.LightningAddress(
                                pubkey=pubkey,
                                host=address,
                            ),
                            perm=False,
                            timeout=20,
                        ))
                    succeeded_nodes.append(pubkey)
                    logger.info("    > connected")
                    break
                except _InactiveRpcError as e:
                    if "already connected" in e.details():
                        succeeded_nodes.append(pubkey)
                        logger.info("    > already connected")
                        break
                    else:
                        logger.info(f"    > error: {e.details()}")
                except Exception as e:
                    logger.exception(e)
                    continue
            else:
                raise ConnectionRefusedError
        return succeeded_nodes

    def pubkey_to_channel_map(self):
        """
        Determines a dict with node pubkeys this node has a channel with, which
        maps to a list of all the channels with the node.

        :return: dictionary of pubkeys with list of channels as value
        :rtype: dict[list]
        """
        channels = self.get_all_channels()

        node_to_channel_map = defaultdict(list)

        for c, cv in channels.items():
            node_to_channel_map[cv['remote_pubkey']].append(c)

        return node_to_channel_map

    def query_mc(self):
        resp = self._routerrpc.QueryMissionControl(
            lndrouter.QueryMissionControlRequest()
        )
        return resp.pairs
