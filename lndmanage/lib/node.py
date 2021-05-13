import os
import codecs
import time
import datetime
import statistics
from typing import List, TYPE_CHECKING

from collections import OrderedDict

import grpc
from grpc._channel import _Rendezvous
from google.protobuf.json_format import MessageToDict

import lndmanage.grpc_compiled.rpc_pb2 as lnd
import lndmanage.grpc_compiled.rpc_pb2_grpc as lndrpc

import lndmanage.grpc_compiled.router_pb2 as lndrouter
import lndmanage.grpc_compiled.router_pb2_grpc as lndrouterrpc

from lndmanage.lib.network import Network
from lndmanage.lib.exceptions import PaymentTimeOut, NoRoute, OurNodeFailure
from lndmanage.lib import exceptions
from lndmanage.lib.utilities import convert_dictionary_number_strings_to_ints
from lndmanage.lib.ln_utilities import (
    extract_short_channel_id_from_string,
    convert_short_channel_id_to_channel_id,
    convert_channel_id_to_short_channel_id,
    channel_unbalancedness_and_commit_fee
)
from lndmanage import settings

if TYPE_CHECKING:
    from lndmanage.lib.routing import Route

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

NUM_MAX_FORWARDING_EVENTS = 100000


class Node(object):
    """Bare node object with attributes."""
    def __init__(self):
        logger.info("Initializing node interface.")
        self.alias = ''
        self.pub_key = ''
        self.total_capacity = 0
        self.total_local_balance = 0
        self.total_remote_balance = 0
        self.total_channels = 0
        self.num_active_channels = 0
        self.num_peers = 0
        self.total_satoshis_received = 0
        self.total_satoshis_sent = 0
        self.total_private_channels = 0
        self.total_active_channels = 0
        self.blockheight = 0
        self.channels = []


class LndNode(Node):
    """
    Implements an interface to an lnd node.
    """
    def __init__(self, config_file=None, lnd_home=None, lnd_host=None,
                 regtest=False):
        """
        :param config_file: path to the config file
        :type config_file: str
        :param lnd_home: path to lnd home folder
        :type lnd_home: str
        :param lnd_host: lnd host of format "127.0.0.1:9735"
        :type lnd_host: str
        :param regtest: if the node is representing a regtest node
        :type regtest: bool
        """
        super().__init__()
        self.config_file = config_file
        self.lnd_home = lnd_home
        self.lnd_host = lnd_host
        self.regtest = regtest

        self._rpc = None
        self._routerrpc = None
        self.connect_rpcs()

        self.network = Network(self)
        self.update_blockheight()
        self.set_info()

    def connect_rpcs(self):
        """
        Establishes a connection to lnd using the hostname, tls certificate,
        and admin macaroon defined in settings.
        """
        macaroons = True
        os.environ['GRPC_SSL_CIPHER_SUITES'] = \
            'ECDHE-RSA-AES128-GCM-SHA256:' \
            'ECDHE-RSA-AES128-SHA256:' \
            'ECDHE-RSA-AES256-SHA384:' \
            'ECDHE-RSA-AES256-GCM-SHA384:' \
            'ECDHE-ECDSA-AES128-GCM-SHA256:' \
            'ECDHE-ECDSA-AES128-SHA256:' \
            'ECDHE-ECDSA-AES256-SHA384:' \
            'ECDHE-ECDSA-AES256-GCM-SHA384'

        # if no lnd_home is given, then use the paths from the config,
        # else override them with default file paths in lnd_home
        if self.lnd_home is not None:
            cert_file = os.path.join(self.lnd_home, 'tls.cert')
            bitcoin_network = 'regtest' if self.regtest else 'mainnet'
            macaroon_file = os.path.join(
                self.lnd_home, 'data/chain/bitcoin/',
                bitcoin_network, 'admin.macaroon')
            if self.lnd_host is None:
                raise ValueError(
                    'if lnd_home is given, lnd_host must be given also')
            lnd_host = self.lnd_host
        else:
            config = settings.read_config(self.config_file)
            cert_file = os.path.expanduser(config['network']['tls_cert_file'])
            macaroon_file = \
                os.path.expanduser(config['network']['admin_macaroon_file'])
            lnd_host = config['network']['lnd_grpc_host']

        cert = None
        try:
            with open(cert_file, 'rb') as f:
                cert = f.read()
        except FileNotFoundError:
            logger.error("tls.cert not found, please configure %s.",
                         self.config_file)
            exit(1)

        if macaroons:
            try:
                with open(macaroon_file, 'rb') as f:
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
            creds = grpc.composite_channel_credentials(cert_creds, auth_creds)

        else:
            creds = grpc.ssl_channel_credentials(cert)

        # necessary to circumvent standard size limitation
        channel = grpc.secure_channel(lnd_host, creds, options=[
            ('grpc.max_receive_message_length', 50 * 1024 * 1024)
        ])

        # establish connections to rpc servers
        self._rpc = lndrpc.LightningStub(channel)
        self._routerrpc = lndrouterrpc.RouterStub(channel)

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

    def send_to_route(self, route: 'Route', payment_hash: bytes,
                      payment_address: bytes):
        """
        Takes bare route (list) and tries to send along it,
        trying to fulfill the invoice labeled by the given hash.

        :param route: (list) of :class:`lib.routes.Route`
        :param payment_hash: invoice identifier
        :return:
        """
        lnd_route = self._to_lnd_route(route)
        # set payment address for last hop
        lnd_route.hops[-1].tlv_payload = True
        lnd_route.hops[-1].mpp_record.payment_addr = payment_address
        lnd_route.hops[-1].mpp_record.total_amt_msat = lnd_route.hops[-1].amt_to_forward_msat
        # set payment hash
        request = lndrouter.SendToRouteRequest(
            route=lnd_route,
            payment_hash=payment_hash,
        )
        try:
            # timeout after 5 minutes
            payment = self._routerrpc.SendToRouteV2(request, timeout=5 * 60)
        except _Rendezvous:
            raise PaymentTimeOut
        if payment.HasField('failure'):
            failure = payment.failure  # type: lnd.Failure.FailureCode
            logger.debug(f"Routing failure: {failure}")
            if failure.failure_source_index == 0:
                raise OurNodeFailure("Not enough funds?")
            if failure.code == 15:
                raise exceptions.TemporaryChannelFailure(payment)
            elif failure.code == 14:
                raise exceptions.ChannelDisabled(payment)
            elif failure.code == 18:
                raise exceptions.UnknownNextPeer(payment)
            elif failure.code == 12:
                raise exceptions.FeeInsufficient(payment)
            else:
                logger.info(failure)
                raise Exception(f"Unknown error: code {failure.code}")

        return payment

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

    def get_open_channels(self, active_only=False, public_only=False):
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

            # determine policy
            try:
                edge_info = self.network.edges[c.chan_id]
                # interested in node2
                if edge_info['node1_pub'] == self.pub_key:
                    policy_peer = edge_info['node2_policy']
                    policy_local = edge_info['node1_policy']
                else:  # interested in node1
                    policy_peer = edge_info['node1_policy']
                    policy_local = edge_info['node2_policy']
            except KeyError:
                # if channel is unknown in describegraph
                # we need to set the fees to some error value
                policy_peer = {'fee_base_msat': float(-999),
                               'fee_rate_milli_msat': float(999)}
                policy_local = {'fee_base_msat': float(-999),
                                'fee_rate_milli_msat': float(999)}

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
                channel_unbalancedness_and_commit_fee(
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

    def get_inactive_channels(self):
        """
        Returns all inactive channels.
        :return: dict of channels
        """
        channels = self.get_open_channels(public_only=False, active_only=False)
        return {k: c for k, c in channels.items() if not c['active']}

    def get_all_channels(self):
        """
        Returns all active and inactive channels.

        :return: dict of channels
        """
        channels = self.get_open_channels(public_only=False, active_only=False)
        return channels

    def get_unbalanced_channels(self, unbalancedness_greater_than=0.0):
        """
        Gets all channels which have an absolute unbalancedness
        (-1...1, -1 for outbound unbalanced, 1 for inbound unbalanced)
        larger than unbalancedness_greater_than.

        :param unbalancedness_greater_than: unbalancedness interval, default returns all channels
        :return: all channels which are more unbalanced than the specified interval
        """
        self.public_active_channels = \
            self.get_open_channels(public_only=True, active_only=True)
        unbalanced_channels = {
            k: c for k, c in self.public_active_channels.items()
            if abs(c['unbalancedness']) >= unbalancedness_greater_than
        }
        return unbalanced_channels

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


if __name__ == '__main__':
    node = LndNode()
    print(node.get_closed_channels().keys())
