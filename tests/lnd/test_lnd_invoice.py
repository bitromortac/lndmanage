import grpc_compiled.rpc_pb2 as ln

from lib.node import LndNode

node = LndNode()
invoice = node.rpc.AddInvoice(ln.Invoice(value=100))
print(invoice)

r_hash = b"\324\233\t\213\205I+\260\320\260 j\347\363\302\211*\376\233\356(\231\013\221>1\371&b\340\017\217"
inv = node.rpc.LookupInvoice(ln.PaymentHash(r_hash=r_hash))
print(str(r_hash.hex()))
