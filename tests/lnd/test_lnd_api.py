from lib.node import LndNode
import grpc_compiled.rpc_pb2 as ln

node = LndNode()

channel = node._stub.GetChanInfo(ln.ChanInfoRequest(chan_id=000000000000000000))
print(channel.node1_policy.fee_base_msat)
