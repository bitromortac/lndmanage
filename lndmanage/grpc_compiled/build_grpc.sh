#!/bin/bash
# git clone https://github.com/googleapis/googleapis.git
# pip install grpcio grpcio-tools googleapis-common-protos
tag="v0.13.1-beta"
wget "https://github.com/lightningnetwork/lnd/raw/${tag}/lnrpc/rpc.proto" -O rpc.proto
wget "https://github.com/lightningnetwork/lnd/raw/${tag}/lnrpc/routerrpc/router.proto" -O router.proto
wget "https://github.com/lightningnetwork/lnd/raw/${tag}/lnrpc/walletrpc/walletkit.proto" -O walletkit.proto
wget "https://github.com/lightningnetwork/lnd/raw/${tag}/lnrpc/signrpc/signer.proto" -O signer.proto

# change signerrpc dependency to match flat file structure
sed -i -- 's@signrpc/@@g' walletkit.proto

# build rpc
python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. rpc.proto
python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. router.proto
python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. walletkit.proto
python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. signer.proto

# fix import paths
sed -i -- 's@import rpc_pb2 as rpc__pb2@from lndmanage.grpc_compiled import rpc_pb2 as rpc__pb2@' rpc_pb2_grpc.py

sed -i -- 's@import signer_pb2 as signer__pb2@from lndmanage.grpc_compiled import signer_pb2 as signer__pb2@' signer_pb2_grpc.py

sed -i -- 's@import router_pb2 as router__pb2@from lndmanage.grpc_compiled import router_pb2 as router__pb2@' router_pb2_grpc.py
sed -i -- 's@import rpc_pb2 as rpc__pb2@from lndmanage.grpc_compiled import rpc_pb2 as rpc__pb2@' router_pb2_grpc.py
sed -i -- 's@import rpc_pb2 as rpc__pb2@from lndmanage.grpc_compiled import rpc_pb2 as rpc__pb2@' router_pb2.py

sed -i -- 's@import rpc_pb2 as rpc__pb2@from lndmanage.grpc_compiled import rpc_pb2 as rpc__pb2@' walletkit_pb2.py
sed -i -- 's@import signer_pb2 as signer__pb2@from lndmanage.grpc_compiled import signer_pb2 as signer__pb2@' walletkit_pb2.py

sed -i -- 's@import signer_pb2 as signer__pb2@from lndmanage.grpc_compiled import signer_pb2 as signer__pb2@' walletkit_pb2_grpc.py
sed -i -- 's@import walletkit_pb2 as walletkit__pb2@from lndmanage.grpc_compiled import walletkit_pb2 as walletkit__pb2@' walletkit_pb2_grpc.py