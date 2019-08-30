lndmanage
---------

lndmanage is a command line tool for advanced channel management of an 
[`LND`](https://github.com/lightningnetwork/lnd) node.

Current feature list (use the ```--help``` flag for subcommands):

* __```status``` advanced node summary__
* __```listchannels``` channel listing commands:__
  * ```listchannels rebalance``` list channels for rebalancing
  * ```listchannels inactive``` list inactive channels for channel hygiene 
  * ```listchannels forwardings``` list forwarding statistics for each channel 
* __```rebalance``` rebalancing of channels:__
  * different strategies can be chosen
  * a target 'balancedness' can be specified (e.g. to empty the channel)
* __```circle``` doing circular self-payments__
* __```recommend-nodes``` recommendation of nodes:__
  * ```recommend-nodes good-old``` based on 
  historic forwardings of closed channels:
  find nodes already interacted with
  * ```recommend-nodes flow-analysis``` based on forwarding flow analysis:
  find nodes payments are likely forwarded to
  * ```recommend-nodes external-source``` based on an external source:
  parses a url/file for node public keys and suggests nodes to connect to for 
  a good connection (defaults to the list of 
  [lightning networkstores](http://lightningnetworkstores.com))
  * ```recommend-nodes channel-openings``` based on recent channel 
  openings in the network: find nodes which show increased recent channel 
  opening activity 
   
**DISCLAIMER: This is BETA software, so please be careful (All actions are 
  executed as a dry run unless you call lndmanage with the ```--reckless``` 
  flag though). No warranty is given.**

Command line options
--------------------
```
usage: lndmanage.py [-h] [--loglevel {INFO,DEBUG}]
                    {status,listchannels,rebalance,circle} ...

Lightning network daemon channel management tool.

positional arguments:
  {status,listchannels,rebalance,circle}
    status              display node status
    listchannels        lists channels with extended information [see also
                        subcommands with -h]
    rebalance           rebalance a channel
    circle              circular self-payment
    recommend-nodes     recommends nodes [see also subcommands with -h]
```

Rebalancing a channel
---------------------
The workflow for rebalancing a channel goes as follows:

* take a look at all your unbalanced channels with:

  ```$ ./lndmanage.py listchannels rebalance```
  
    The output will look like:
  ```
  -------- Description --------
  ub         unbalancedness (see --help)
  cap        channel capacity [sat]
  lb         local balance [sat]
  rb         remote balance [sat]
  bf         peer base fee [msat]
  fr         peer fee rate
  cid        channel id
  a          alias
  
  -------- Channels --------
         cid            ub       cap        lb        rb     bf        fr  a       
  xxxxxxxxxxxxxxxxxx -0.78   1000000    888861     99480     10  0.000200 abc                
  xxxxxxxxxxxxxxxxxx -0.63   1000000    814537    173768    300  0.000010 def
  xxxxxxxxxxxxxxxxxx  0.55   2000000    450792   1540038     35  0.000002 ghi
  xxxxxxxxxxxxxxxxxx  0.59    400000     81971    306335    400  0.000101 jkl
  ...
  ```
* the ```ub``` field tells you how unbalanced your channel is 
  and in which direction
* take a channel_id from the list you wish
  to rebalance (target is a 50:50 balance)
* do a dry run to see what's waiting for you

  ```$ ./lndmange.py rebalance --max-fee-sat 20 --max-fee-rate 0.00001 channel_id```

* read the output and if everything looks well, 
  then run with the ```--reckless``` flag
* in order to increase the success probability of your rebalancing you
  can try to do it in smaller chunks, which can be set by the flag
  `--chunksize 0.5` (in this example only half the amounts are used)

Channel hygiene
---------------------
Inactive channels lock up capital, which can be used elsewhere. 
In order to close those channels it is useful to take a look
at the inactive channels with ```$ ./lndmanage.py listchannels inactive```.

You will get an output like:

```
-------- Description --------
p          true if private channel
ini        true if we opened channel
lup        last update time [days ago]
age        channel age [days]
cap        capacity [sat]
lb         local balance [sat]
sr/w       satoshis sent + received per week of lifespan
cid        channel id
a          alias

-------- Channels --------
       cid         p ini   lup   age       cap        lb     sr/w  a       
xxxxxxxxxxxxxxxxxx F   F    66    71   2000000     10000      100 abc
xxxxxxxxxxxxxxxxxx T   F    20   113     40000         0        0 def
xxxxxxxxxxxxxxxxxx F   T    19    21   1200000      1000        0 ghi
...
```
Channels, which were updated a long time ago (```lup```) are likely to be 
inactive in the future and may be closed.

Another way to see if funds have to be reallocated is to have a look at
the forwarding statistics of, e.g., the last two months of the individual 
channels with ```$./lndmanage.py listchannels forwardings --from-days-ago 60 --sort-by='fees'```
 (here sorted by total fees, but it can be sorted by any column field).

The output will look like:
```
-------- Description --------
cid        channel id
nfwd       number of forwardings
age        channel age [days]
fees       fees total [sat]
f/w        fees per week [sat]
ub         unbalancedness
flow       flow direction (positive is outwards)
bwd        bandwidth demand: capacity / max(mean_in, mean_out)
r          rebalance required if marked with X
cap        channel capacity [sat]
in         total forwardings inwards [sat]
imean      mean forwarding inwards [sat]
imax       largest forwarding inwards [sat]
out        total forwardings outwards [sat]
omean      mean forwarding outwards [sat]
omax       largest forwarding outwards [sat]
a          alias

-------- Channels --------
       cid         nfwd   age  fees     f/w    ub  flow  bwd r      cap       in   imean    imax      out   omean    omax  a
xxxxxxxxxxxxxxxxxx    6   103   907 106.950  0.30  1.00 0.00 X  6000000        0     nan     nan  1935309   20000 1800902 abc
xxxxxxxxxxxxxxxxxx    3    82   300  35.374  0.74 -0.08 0.70    1000000   700008  700008  700008   600000  600000  600000 def
xxxxxxxxxxxxxxxxxx    4    32   216  25.461  0.38  0.42 0.17 X  6000000   993591  993591  993591  2450000  750000 1000000 ghi
...
```

Channel opening strategies
--------------------------
Lndmanage supports a channel annotation functionality. By adding the funding
transaction id or channel id to the file `channel_annotations` specified by the
format in the file, a comment on why one has opened a specific channel can be
remembered. These annotations will then appear in the `listchannels` views.

Setup
-----
Lndmanage will be developed in lockstep with lnd and tagged accordingly. 
If you are running an older version of lnd checkout the according 
[tag](https://github.com/bitromortac/lndmanage/releases).

Requirements: python3.6, lnd v0.7.0-beta
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

Before running, make sure the python environment is active:
```
$ source ~/.venvs/lndmanage/bin/activate
$ ./lndmanage.py status 
```
If it works, you should see the node status.

Testing
-------
Requirements are an installation of [lnregtest](https://github.com/bitromortac/lnregtest)
and links to bitcoind, bitcoin-cli, lnd, and lncli in the `test/bin` folder.

Tests can be run with
`python3 -m unittest discover test`
from the root folder.

Docker
------

If you prefer to run `lndmanage` from a docker container, `cd docker` 
and follow [`README`](docker/README.md) there.

Compiling grpc in python [development]
----------------------------------------------------
```
$ cd grpc_compiled
$ pip install grpcio grpcio-tools googleapis-common-protos
$ git clone https://github.com/googleapis/googleapis.git
$ curl -o rpc.proto -s https://raw.githubusercontent.com/lightningnetwork/lnd/master/lnrpc/rpc.proto
$ python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. rpc.proto
```
