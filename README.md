lndmanage
---------

Control tool for lightning network daemon ([`lnd`](https://github.com/lightningnetwork/lnd)) node operators, optimized for remote control.

**DISCLAIMER: This is BETA software, so please be careful (there are --dry run flags). No warranty is given.**

Current feature list (use --help flags for subcommands):

* display status summary [./lndmange.py status]
* display channel summary [./lndmange.py listchannels]
* rebalancing of channels [./lndmanage.py rebalance channel_id]
* do circular self-payments [./lndmanage.py circle channel_from channel_to amt_sats]

Setup
-----
Requirements: python3.6, lnd 0.6
```
$ virtualenv -p python3 ~/.venvs/lndmanage
$ source ~/.venvs/lndmanage/bin/activate
$ git clone https://github.com/bitromortac/lndmanage
$ cd lndmanage
$ pip install -r requirements.txt
$ cp config_sample.ini config.ini
```

Edit configuration (config.ini):
* lnd_grpc_host: ip and port of the grpc API
* tls_cert_file: location of the tls certificate
* admin_macaroon_file: location of the admin macaroon

Test:
```
$ ./lndmanage.py status 
```
If if works, you should see the node status and a list of channels.

Rebalancing a channel
---------------------
The workflow for rebalancing a channels goes as follows:

* take a look at all your unbalanced channels with:

  ```$ ./lndmanage.py listchannels --unbalancedness 0.5```
* take a channel_id from the list you wish to rebalance (target is a 50:50 balance)
* do a dry run to see what's waiting for you

  ```$ ./lndmange.py rebalance --dry --max-fee-sat 20 --max-fee-rate 0.00001 channel_id```

* read the output and if everything is looking well, then run without the "--dry" flag


Compiling grpc in python [development]
----------------------------------------------------
```
$ cd grpc_compile
$ pip install grpcio grpcio-tools googleapis-common-protos
$ git clone https://github.com/googleapis/googleapis.git
$ curl -o rpc.proto -s https://raw.githubusercontent.com/lightningnetwork/lnd/master/lnrpc/rpc.proto
$ python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. rpc.proto
```
