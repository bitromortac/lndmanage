#!/bin/bash
git clone https://github.com/googleapis/googleapis.git
python -m venv temp
source temp/bin/activate
pip install --upgrade pip
pip install grpcio==1.51.3 grpcio-tools==1.48.2 googleapis-common-protos==1.58.0 protobuf==3.20.3

tag="v0.15.5-beta"

wget "https://raw.githubusercontent.com/lightningnetwork/lnd/${tag}/lnrpc/lightning.proto" -O lightning.proto
wget "https://raw.githubusercontent.com/lightningnetwork/lnd/${tag}/lnrpc/routerrpc/router.proto" -O router.proto
wget "https://raw.githubusercontent.com/lightningnetwork/lnd/${tag}/lnrpc/walletrpc/walletkit.proto" -O walletkit.proto
wget "https://raw.githubusercontent.com/lightningnetwork/lnd/${tag}/lnrpc/signrpc/signer.proto" -O signer.proto

# change signerrpc dependency to match flat file structure
sed -i -- 's@signrpc/@@g' walletkit.proto

# build rpc
python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. lightning.proto
python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. router.proto
python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. walletkit.proto
python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. signer.proto

# fix import paths
sed -i -- 's@import lightning_pb2 as lightning__pb2@from lndmanage.grpc_compiled import lightning_pb2 as lightning__pb2@' lightning_pb2_grpc.py

sed -i -- 's@import signer_pb2 as signer__pb2@from lndmanage.grpc_compiled import signer_pb2 as signer__pb2@' signer_pb2_grpc.py

sed -i -- 's@import router_pb2 as router__pb2@from lndmanage.grpc_compiled import router_pb2 as router__pb2@' router_pb2_grpc.py
sed -i -- 's@import lightning_pb2 as lightning__pb2@from lndmanage.grpc_compiled import lightning_pb2 as lightning__pb2@' router_pb2_grpc.py
sed -i -- 's@import lightning_pb2 as lightning__pb2@from lndmanage.grpc_compiled import lightning_pb2 as lightning__pb2@' router_pb2.py

sed -i -- 's@import lightning_pb2 as lightning__pb2@from lndmanage.grpc_compiled import lightning_pb2 as lightning__pb2@' walletkit_pb2.py
sed -i -- 's@import signer_pb2 as signer__pb2@from lndmanage.grpc_compiled import signer_pb2 as signer__pb2@' walletkit_pb2.py

sed -i -- 's@import signer_pb2 as signer__pb2@from lndmanage.grpc_compiled import signer_pb2 as signer__pb2@' walletkit_pb2_grpc.py
sed -i -- 's@import walletkit_pb2 as walletkit__pb2@from lndmanage.grpc_compiled import walletkit_pb2 as walletkit__pb2@' walletkit_pb2_grpc.py
