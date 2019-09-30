import os
import codecs
import time
import datetime
from collections import OrderedDict

import grpc
from grpc._channel import _Rendezvous
from google.protobuf.json_format import MessageToDict

import lndmanage.grpc_compiled.rpc_pb2 as ln
import lndmanage.grpc_compiled.rpc_pb2_grpc as lnrpc
from lndmanage.lib.network import Network
from lndmanage.lib.exceptions import PaymentTimeOut, NoRouteError
from lndmanage.lib.utilities import convert_dictionary_number_strings_to_ints
from lndmanage.lib.ln_utilities import (
    extract_short_channel_id_from_string,
    convert_short_channel_id_to_channel_id,
    convert_channel_id_to_short_channel_id,
    channel_unbalancedness_and_commit_fee
)
from lndmanage import settings

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
        super().__init__()
        self.config_file = config_file
        self.lnd_home = lnd_home
        self.lnd_host = lnd_host
        self.regtest = regtest
        self._stub = self.connect()
        self.network = Network(self)
        self.update_blockheight()
        self.set_info()

    def connect(self):
        """
        Establishes a connection to lnd using the hostname, tls certificate,
        and admin macaroon defined in settings.
        """
        macaroons = True
        os.environ['GRPC_SSL_CIPHER_SUITES'] = '' + \
                                               'ECDHE-RSA-AES128-GCM-SHA256:' + \
                                               'ECDHE-RSA-AES128-SHA256:' + \
                                               'ECDHE-RSA-AES256-SHA384:' + \
                                               'ECDHE-RSA-AES256-GCM-SHA384:' + \
                                               'ECDHE-ECDSA-AES128-GCM-SHA256:' + \
                                               'ECDHE-ECDSA-AES128-SHA256:' + \
                                               'ECDHE-ECDSA-AES256-SHA384:' + \
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
                raise ValueError('if lnd_home is given, lnd_host must be given also')
            lnd_host = self.lnd_host
        else:
            config = settings.read_config(self.config_file)
            cert_file = os.path.expanduser(config['network']['tls_cert_file'])
            macaroon_file = os.path.expanduser(config['network']['admin_macaroon_file'])
            lnd_host = config['network']['lnd_grpc_host']

        try:
            with open(cert_file, 'rb') as f:
                cert = f.read()
        except FileNotFoundError as e:
            logger.error("tls.cert not found, please configure %s.",
                         self.config_file)
            exit(1)

        if macaroons:
            try:
                with open(macaroon_file, 'rb') as f:
                    macaroon_bytes = f.read()
                    macaroon = codecs.encode(macaroon_bytes, 'hex')
            except FileNotFoundError as e:
                logger.error("admin.macaroon not found, please configure %s.",
                             self.config_file)
                exit(1)

            def metadata_callback(context, callback):
                # for more info see grpc docs
                callback([('macaroon', macaroon)], None)

            cert_creds = grpc.ssl_channel_credentials(cert)
            auth_creds = grpc.metadata_call_credentials(metadata_callback)
            creds = grpc.composite_channel_credentials(cert_creds, auth_creds)

        else:
            creds = grpc.ssl_channel_credentials(cert)

        channel = grpc.secure_channel(lnd_host, creds, options=[
            ('grpc.max_receive_message_length', 50 * 1024 * 1024)  # necessary to circumvent standard size limitation
        ])

        return lnrpc.LightningStub(channel)

    def update_blockheight(self):
        info = self._stub.GetInfo(ln.GetInfoRequest())
        self.blockheight = int(info.block_height)

    def get_channel_info(self, channel_id):
        channel = self._stub.GetChanInfo(ln.ChanInfoRequest(chan_id=channel_id))
        channel_dict = MessageToDict(channel, including_default_value_fields=True)
        channel_dict = convert_dictionary_number_strings_to_ints(channel_dict)
        return channel_dict

    @staticmethod
    def lnd_hops(hops):
        return [ln.Hop(**hop) for hop in hops]

    def lnd_route(self, route):
        """
        Converts a cleartext route to an lnd route.

        :param route: :class:`lib.route.Route`
        :return:
        """
        hops = self.lnd_hops(route.hops)
        return ln.Route(
            total_time_lock=route.total_time_lock,
            total_fees=route.total_fee_msat // 1000,
            total_amt=route.total_amt_msat // 1000,
            hops=hops,
            total_fees_msat=route.total_fee_msat,
            total_amt_msat=route.total_amt_msat
        )

    def self_payment(self, routes, amt_msat):
        """
        Do a self-payment along routes with amt_msat.

        :param routes: list of :class:`lib.route.Route` objects
        :param amt_msat:
        :return: payment result
        """
        invoice = self._stub.AddInvoice(ln.Invoice(value=amt_msat // 1000))
        result = self.send_to_route(routes, invoice.r_hash)
        logger.debug(result)
        return result

    def self_payment_zero_invoice(self, routes, memo):
        """
        Do a self-payment along routes with an invoice of zero satoshis.
        This helps to use one invoice for several rebalancing attempts.
        Adds a memo to the invoice, which can later be parsed for bookkeeping.

        :param routes: list of :class:`lib.route.Route` objects
        :param memo: str, Comment field for an invoice.
        :return: payment result
        """
        invoice = self._stub.AddInvoice(ln.Invoice(value=0, memo=memo))
        result = self.send_to_route(routes, invoice.r_hash)
        logger.debug(result)
        return result

    def get_invoice(self, amt_msat, memo):
        """
        Creates a new invoice with amt_msat and memo.

        :param amt_msat: int
        :param memo: str
        :return: Hash of invoice preimage.
        """
        invoice = self._stub.AddInvoice(
            ln.Invoice(value=amt_msat // 1000, memo=memo))
        return invoice.r_hash

    def get_rebalance_invoice(self, memo):
        """
        Creates a zero amount invoice and gives back it's hash.

        :param memo: Comment for the invoice.
        :return: Hash of the invoice preimage.
        """
        invoice = self._stub.AddInvoice(ln.Invoice(value=0, memo=memo))
        return invoice.r_hash

    def send_to_route(self, route, r_hash_bytes):
        """
        Takes bare route (list) and tries to send along it,
        trying to fulfill the invoice labeled by the given hash.

        :param route: (list) of :class:`lib.routes.Route`
        :param r_hash_bytes: invoice identifier
        :return:
        """
        lnd_route = self.lnd_route(route)
        request = ln.SendToRouteRequest(
            route=lnd_route,
            payment_hash_string=r_hash_bytes.hex(),
        )
        try:
            return self._stub.SendToRouteSync(request, timeout=5*60)  # timeout after 5 minutes
        except _Rendezvous:
            raise PaymentTimeOut

    def get_raw_network_graph(self):
        try:
            graph = self._stub.DescribeGraph(ln.ChannelGraphRequest())
        except _Rendezvous:
            logger.error(
                "Problem connecting to lnd. "
                "Either %s is not configured correctly or lnd is not running.",
                self.config_file)
            exit(1)
        return graph

    def get_raw_info(self):
        """
        Returns specific information about this node.

        :return: node information
        """
        return self._stub.GetInfo(ln.GetInfoRequest())

    def set_info(self):
        """
        Fetches information about this node and computes total capacity,
        local and remote total balance, how many satoshis were sent and received,
        and some networking peer stats.
        """

        raw_info = self.get_raw_info()
        self.pub_key = raw_info.identity_pubkey
        self.alias = raw_info.alias
        self.num_active_channels = raw_info.num_active_channels
        self.num_peers = raw_info.num_peers

        # TODO: remove the following code and implement an advanced status
        all_channels = self.get_open_channels(active_only=False, public_only=False)

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
        Fetches information (fee settings of the counterparty, channel capacity, balancedness)
         about this node's open channels and saves it into the channels dict attribute.

        :param active_only: bool, only take active channels into account (default)
        :param public_only: bool, only take public channels into account (off by default)
        :return: list of channels sorted by remote pubkey
        """
        raw_channels = self._stub.ListChannels(ln.ListChannelsRequest(active_only=active_only, public_only=public_only))
        channels_data = raw_channels.ListFields()[0][1]
        channels = OrderedDict()

        for c in channels_data:
            # calculate age from blockheight
            blockheight, _, _ = convert_channel_id_to_short_channel_id(c.chan_id)
            age_days = (self.blockheight - blockheight) * 10 / (60 * 24)
            # calculate last update (days ago)
            try:
                last_update = (time.time() - self.network.edges[c.chan_id]['last_update']) / (60 * 60 * 24)
            except TypeError:
                last_update = float('nan')
            except KeyError:
                last_update = float('nan')

            sent_received_per_week = int((c.total_satoshis_sent + c.total_satoshis_received) / (age_days / 7))
            # determine policy

            try:
                edge_info = self.network.edges[c.chan_id]
                if edge_info['node1_pub'] == self.pub_key:  # interested in node2
                    policy = edge_info['node2_policy']
                else:  # interested in node1
                    policy = edge_info['node1_policy']
            except KeyError:
                # TODO: if channel is unknown in describegraph we need to set the fees to some error value
                policy = {'fee_base_msat': float(-999),
                          'fee_rate_milli_msat': float(999)}

            # define unbalancedness |ub| large means very unbalanced
            channel_unbalancedness, our_commit_fee = channel_unbalancedness_and_commit_fee(
                c.local_balance, c.capacity, c.commit_fee, c.initiator)

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
                'peer_base_fee': policy['fee_base_msat'],
                'peer_fee_rate': policy['fee_rate_milli_msat'],
                'initiator': c.initiator,
                'last_update': last_update,
                'local_balance': c.local_balance,
                'num_updates': c.num_updates,
                'private': c.private,
                'remote_balance': c.remote_balance,
                'remote_pubkey': c.remote_pubkey,
                'sent_received_per_week': sent_received_per_week,
                'total_satoshis_sent': c.total_satoshis_sent,
                'total_satoshis_received': c.total_satoshis_received,
                'unbalancedness': channel_unbalancedness,
            }
        sorted_dict = OrderedDict(sorted(channels.items(), key=lambda x: x[1]['alias']))
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

        forwardings = self._stub.ForwardingHistory(ln.ForwardingHistoryRequest(
            start_time=then,
            end_time=now,
            num_max_events=NUM_MAX_FORWARDING_EVENTS))

        events = [{
            'timestamp': f.timestamp,
            'chan_id_in': f.chan_id_in,
            'chan_id_out': f.chan_id_out,
            'amt_in': f.amt_in,
            'amt_out': f.amt_out,
            'fee_msat': f.fee_msat,
            'effective_fee': f.fee_msat / (f.amt_in * 1000)
        } for f in forwardings.forwarding_events]

        return events

    def get_closed_channels(self):
        """
        Fetches all closed channels.

        :return: dict, channel list
        """
        request = ln.ClosedChannelsRequest()
        closed_channels = self._stub.ClosedChannels(request)
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
                            ignored_nodes=(), ignored_channels={}):
        """
        Queries the lnd node for a route. Channels and nodes can be ignored if they failed before.

        :param source_pubkey: str
        :param target_pubkey: str
        :param amt_msat: int
        :param ignored_nodes: list of node pub keys
        :param ignored_channels: dict
        :return: list of channel_ids
        """
        amt_sat = amt_msat// 1000

        # we want to see all routes:
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
                    ln.EdgeLocator(channel_id=c,
                                   direction_reverse=direction_reverse))
        else:
            ignored_channels_api = []

        logger.debug(f"Ignored for queryroutes: channels: "
                     f"{ignored_channels_api}, nodes: {ignored_nodes_api}")

        request = ln.QueryRoutesRequest(
            pub_key=target_pubkey,
            amt=amt_sat,
            final_cltv_delta=0,
            fee_limit=ln.FeeLimit(fixed=max_fee),
            ignored_nodes=ignored_nodes_api,
            ignored_edges=ignored_channels_api,
            source_pub_key=source_pubkey,
        )
        try:
            response = self._stub.QueryRoutes(request)
        except _Rendezvous:
            raise NoRouteError
        # print(response)
        # We give back only one route, as multiple routes will be deprecated
        channel_route = [h.chan_id for h in response.routes[0].hops]

        return channel_route

    def print_status(self):
        logger.info("-------- Node status --------")
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
