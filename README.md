lndmanage
---------

Control tool for lightning network daemon ([`LND`](https://github.com/lightningnetwork/lnd)) node operators, optimized for remote control.

**DISCLAIMER: This is BETA software, so please be careful (All actions are executed as a dry run unless you call lndmanage with the ```--reckless``` flag though). No warranty is given.**

Current feature list (use --help flags for subcommands):

* advanced node summary ```$ ./lndmange.py status```
* compact listchannels commands ```$ ./lndmange.py listchannels```
  * list channels for rebalancing ```$ ./lndmange.py listchannels rebalance```
  * list inactive channels for channel hygiene ```$ ./lndmange.py listchannels hygiene```
* rebalancing of channels ```$ ./lndmanage.py rebalance channel_id```
* do circular self-payments ```$ ./lndmanage.py circle channel_from channel_to amt_sats```

Rebalancing a channel
---------------------
The workflow for rebalancing a channels goes as follows:

* take a look at all your unbalanced channels with:

  ```$ ./lndmanage.py listchannels rebalance```
  
  The output will look like:
  ```
  -------- Description --------
  cid: channel id
  ub: unbalancedness (see --help)
  c: channel capacity [sats]
  l: local balance [sats]
  r: remote balance [sats]
  bf: peer base fee [msats]
  fr: peer fee rate
  a: alias
  -------- Channels --------
  cid:XXXXXXXXXXXXXXXXXX ub:-0.78 c:  1000000 l:   889804 r:    99480 bf:     0 fr: 0.000100 a:abc
  cid:XXXXXXXXXXXXXXXXXX ub:-0.62 c:  1000000 l:   811899 r:   176868 bf:   500 fr: 0.000002 a:def
  cid:XXXXXXXXXXXXXXXXXX ub:-0.53 c:  5000000 l:  3823599 r:  1165163 bf:  1200 fr: 0.004000 a:ghi
  cid:XXXXXXXXXXXXXXXXXX ub: 0.51 c:  4000000 l:   983961 r:  3005320 bf:     3 fr: 0.000030 a:jkl
  cid:XXXXXXXXXXXXXXXXXX ub: 0.55 c:  2000000 l:   450792 r:  1538492 bf:    30 fr: 0.000004 a:mno
  ...
  ```
* the ```ub``` field tells you how unbalanced your channel is and in which direction
* take a channel_id from the list you wish to rebalance (target is a 50:50 balance)
* do a dry run to see what's waiting for you

  ```$ ./lndmange.py rebalance --max-fee-sat 20 --max-fee-rate 0.00001 channel_id```

* read the output and if everything looks well, then run with the ```--reckless``` flag

Doing channel hygiene
---------------------
Inactive channels lock up capital, which can be used elsewhere. In order to close those channels it is useful to take a look
at the inactive channels with ```$ ./lndmanage.py listchannels hygiene```.

You will get an output like:

```
-------- Description --------
cid: channel id
p: true if private channel
o: true if we opened channel
upd: last update time [days ago]
age: channel age [days]
c: capacity [sats]
l: local balance [sats]
sr/w: satoshis sent + received per week of lifespan
a: alias
-------- Channels --------
cid:XXXXXXXXXXXXXXXXXX p:F o:F upd: 49 age:  54 c:  3700000 l:        0 sr/w:       0 a:XYZ
cid:XXXXXXXXXXXXXXXXXX p:F o:F upd: 16 age:  99 c:    20000 l:        0 sr/w:       0 a:ABC
...
```
Channels, which were updated a long time ago are likely to be inactive in the future and may be closed.

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
If if works, you should see the node status.

Compiling grpc in python [development]
----------------------------------------------------
```
$ cd grpc_compile
$ pip install grpcio grpcio-tools googleapis-common-protos
$ git clone https://github.com/googleapis/googleapis.git
$ curl -o rpc.proto -s https://raw.githubusercontent.com/lightningnetwork/lnd/master/lnrpc/rpc.proto
$ python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. rpc.proto
```
