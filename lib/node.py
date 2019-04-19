import os
import codecs
import time
import datetime

import grpc
from grpc._channel import _Rendezvous

import grpc_compiled.rpc_pb2 as ln
import grpc_compiled.rpc_pb2_grpc as lnrpc
from google.protobuf.json_format import MessageToDict

import _settings

from lib.network import Network
from lib.utilities import convert_dictionary_number_strings_to_ints
from lib.ln_utilities import extract_short_channel_id_from_string, convert_short_channel_id_to_channel_id
from lib.exceptions import PaymentTimeOut, NoRouteError

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

NUM_MAX_FORWARDING_EVENTS = 10000


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
    def __init__(self):
        super().__init__()
        self._stub = self.connect()
        self.network = Network(self)
        self.public_active_channels = self.get_channels(public_only=True, active_only=True)
        self.set_info()
        self.update_blockheight()

    @staticmethod
    def connect():
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

        cert = open(os.path.expanduser(_settings.config['network']['tls_cert_file']), 'rb').read()

        if macaroons:
            with open(os.path.expanduser(_settings.config['network']['admin_macaroon_file']), 'rb') as f:
                macaroon_bytes = f.read()
                macaroon = codecs.encode(macaroon_bytes, 'hex')

            def metadata_callback(context, callback):
                # for more info see grpc docs
                callback([('macaroon', macaroon)], None)

            cert_creds = grpc.ssl_channel_credentials(cert)
            auth_creds = grpc.metadata_call_credentials(metadata_callback)
            creds = grpc.composite_channel_credentials(cert_creds, auth_creds)

        else:
            creds = grpc.ssl_channel_credentials(cert)

        channel = grpc.secure_channel(_settings.config['network']['lnd_grpc_host'], creds, options=[
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

    def get_invoice(self, amt_msat):
        """
        Fetches an already created invoice from lnd.

        :param amt_msat:
        :return: Hash of invoice preimage.
        """
        invoice = self._stub.AddInvoice(ln.Invoice(value=amt_msat // 1000))
        return invoice.r_hash

    def get_rebalance_invoice(self, memo):
        """
        Creates a zero amount invoice and gives back it's hash.

        :param memo: Comment for the invoice.
        :return: Hash of the invoice preimage.
        """
        invoice = self._stub.AddInvoice(ln.Invoice(value=0, memo=memo))
        return invoice.r_hash

    def send_to_route(self, routes, r_hash_bytes):
        """
        Takes bare route (list) and tries to send along it,
        trying to fulfill the invoice labeled by the given hash.

        :param routes: (list) of :class:`lib.routes.Route`
        :param r_hash_bytes: invoice identifier
        :return:
        """
        if type(routes) == list:
            lnd_routes = [self.lnd_route(route) for route in routes]
        else:
            lnd_routes = [self.lnd_route(routes)]
        request = ln.SendToRouteRequest(
            routes=lnd_routes,
            payment_hash_string=r_hash_bytes.hex(),
        )
        try:
            return self._stub.SendToRouteSync(request, timeout=5*60)  # timeout after 5 minutes
        except _Rendezvous:
            raise PaymentTimeOut

    def get_raw_network_graph(self):
        graph = self._stub.DescribeGraph(ln.ChannelGraphRequest())
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
        all_channels = self.get_channels(active_only=False, public_only=False)

        for c in all_channels:
            self.total_capacity += c['capacity']
            self.total_local_balance += c['local_balance']
            self.total_remote_balance += c['remote_balance']
            self.total_satoshis_received += c['total_satoshis_received']
            self.total_satoshis_sent += c['total_satoshis_sent']
            if c['active']:
                self.total_active_channels += 1
            if c['private']:
                self.total_private_channels += 1
            self.alias = raw_info.alias
            self.pub_key = raw_info.identity_pubkey
            self.total_channels = len(self.public_active_channels)
            self.num_active_channels = raw_info.num_active_channels
            self.num_peers = raw_info.num_peers

    def get_channels(self, active_only=True, public_only=False):
        """
        Fetches information (fee settings of the counterparty, channel capacity, balancedness)
         about this node's open channels and saves it into the channels dict attribute.

        :param active_only: bool, only take active channels into account (default)
        :param public_only: bool, only take public channels into account (off by default)
        :return: list of channels sorted by remote pubkey
        """
        raw_channels = self._stub.ListChannels(ln.ListChannelsRequest(active_only=active_only, public_only=public_only))
        channels_data = raw_channels.ListFields()[0][1]
        channels = []
        for c in channels_data:
            if self.pub_key < c.remote_pubkey:  # interested in node1
                policy_node = 'node1_policy'
            else:  # interested in node2
                policy_node = 'node2_policy'

            try:
                policy = self.network.edges[c.chan_id][policy_node]
            except KeyError:
                policy = {'fee_base_msat': -1,
                          'fee_rate_milli_msat': -1}
            unbalancedness = -(float(c.local_balance) / c.capacity - 0.5) / 0.5

            try:
                last_update = self.network.edges[c.chan_id]['last_update']
            except KeyError:
                # TODO: lncli describegraph doesn't know about private channels
                last_update = None

            channels.append({
                'active': c.active,
                'alias': self.network.get_node_alias(c.remote_pubkey),
                'amt_to_balanced': int(abs(unbalancedness * c.capacity / 2)),
                'capacity': c.capacity,
                'chan_id': c.chan_id,
                'channel_point': c.channel_point,
                'commit_fee': c.commit_fee,
                'fees': {'base': policy['fee_base_msat'], 'rate': policy['fee_rate_milli_msat']},
                'initiator': c.initiator,
                'last_update': last_update,
                'local_balance': c.local_balance,
                'num_updates': c.num_updates,
                'private': c.private,
                'relative_local_balance': float(c.local_balance) / float(c.capacity),
                'remote_pubkey': c.remote_pubkey,
                'total_satoshis_sent': c.total_satoshis_sent,
                'total_satoshis_received': c.total_satoshis_received,
                'remote_balance': c.remote_balance,
                'unbalancedness': unbalancedness,
            })
        return sorted(channels, key=lambda x: x['remote_pubkey'])

    def get_inactive_channels(self):
        channels = self.get_channels(public_only=False, active_only=False)
        return [c for c in channels if not c['active']]

    def get_unbalanced_channels(self, unbalancedness_greater_than=0.0):
        """
        Gets all channels which have an absolute unbalancedness
        (-1...1, -1 for outbound unbalanced, 1 for inbound unbalanced)
        larger than unbalancedness_greater_than.

        :param unbalancedness_greater_than: unbalancedness interval, default returns all channels
        :return: all channels which are more unbalanced than the specified interval
        """
        unbalanced_channels = []
        for c in self.public_active_channels:
            if abs(c['unbalancedness']) >= unbalancedness_greater_than:
                unbalanced_channels.append(c)
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

    def queryroute_external(self, source_pubkey, target_pubkey, amt_msat, ignored_nodes=(), ignored_channels=()):
        """
        Queries the lnd node for a route. Channels and nodes can be ignored if they failed before.

        :param source_pubkey: str
        :param target_pubkey: str
        :param amt_msat: int
        :param ignored_nodes: list of node pub keys
        :param ignored_channels: list of channel_ids
        :return: list of channel_ids
        """
        amt_sat = amt_msat // 1000

        # we want to see all routes:
        max_fee = 10000

        # convert ignored nodes to api format
        if ignored_nodes:
            ignored_nodes_api = [bytes.fromhex(n) for n in ignored_nodes]
        else:
            ignored_nodes_api = []

        # convert ignored channels to api format
        if ignored_channels:
            ignored_channels_api = [ln.EdgeLocator(channel_id=c) for c in ignored_channels]
        else:
            ignored_channels_api = []

        logger.debug(f"Ignored for queryroutes: channels: {ignored_channels_api}, nodes: {ignored_nodes_api}")

        request = ln.QueryRoutesRequest(
            pub_key=target_pubkey,
            amt=amt_sat,
            num_routes=1,
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
    print(node.get_channel_info(000000000000000000))
