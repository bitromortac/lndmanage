import unittest
import codecs

from lib.node import LndNode
import grpc_compiled.rpc_pb2 as ln


class TestLndAPI(unittest.TestCase):
    def setUp(self):
        self.node = LndNode()

    def test_chan_info_request(self):
        channel = self.node._stub.GetChanInfo(ln.ChanInfoRequest(chan_id=000000000000000000))
        print(channel.node1_policy.fee_base_msat)

    def test_queryroutes(self):
        request = ln.QueryRoutesRequest(
            pub_key='100000000000000000000000000000000000000000000000000000000000000000',
            amt=100,
            num_routes=1,
            final_cltv_delta=0,
            fee_limit=ln.FeeLimit(fixed=20),
            ignored_nodes=[bytes.fromhex('200000000000000000000000000000000000000000000000000000000000000000')],
            ignored_edges=[ln.EdgeLocator(channel_id=000000000000000000)],
            source_pub_key='300000000000000000000000000000000000000000000000000000000000000000',
        )

        response = self.node._stub.QueryRoutes(request)
        print(response)
