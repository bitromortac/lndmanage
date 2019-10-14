lndmanage
---------

lndmanage is a command line tool for advanced channel management of an 
[`LND`](https://github.com/lightningnetwork/lnd) node.

Current feature list (use the ```--help``` flag for subcommands):

* __Activity reports ```report```__
* __Display the node summary ```status```__
* __Advanced channel listings ```listchannels```__
  * ```listchannels rebalance```: list channels for rebalancing
  * ```listchannels inactive```: list inactive channels for channel hygiene 
  * ```listchannels forwardings```: list forwarding statistics for each channel 
* __Rebalancing command ```rebalance```__
  * different rebalancing strategies can be chosen
  * a target 'balancedness' can be specified (e.g. to empty the channel)
* __Circular self-payments ```circle```__
* __Recommendation of good nodes ```recommend-nodes```__
   
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
    circle              circular self-payment
    listchannels        lists channels with extended information [see also
                        subcommands with -h]
    rebalance           rebalance a channel
    recommend-nodes     recommends nodes [see also subcommands with -h]
    report              displays reports of activity on the node
    status              display node status
```

Activity Report
---------------
With lndmanage you can get a compact overview of what happened during the last
day(s). It will show you forwarding activity (total forwardings, forwarding fees,
and forwarding amounts) as well as channel opening and closing events by invoking

`$ lndmanage report`

Different time intervals can be specified with the `--from-days-ago` and 
`--to-days-ago` flags.

Here is a sample report for one of the subreports. The activity histogram for 
the time interval is displayed as a one-line histogram, which consists of 
Braille-like characters.
```
Report from yyyy-mm-dd hh:mm to yyyy-mm-dd hh:mm

Forwardings:
   activity (⣿ represents 8 forwardings):

   |⠀⠀⡀⡀⠀⠀⠀⠀⠀⠀⡀⠀⠀⠀⠀⠀⠀⣄⠀⣀⠀⣦⣀⠀⡀⡀⠀⡀⡀⠀⡀⠀⠀⠀⠀⠀⠀⣀⣀⡀⣀⡀⡀⣀⠀⣀⡀⣄|

   total forwardings: 37
   forwardings per day: 37

   channels with most outgoing forwardings:
   cidxxxxxxxxxxxxxxx: 10
   cidxxxxxxxxxxxxxxx: 6
   cidxxxxxxxxxxxxxxx: 4
   cidxxxxxxxxxxxxxxx: 3
   cidxxxxxxxxxxxxxxx: 3
```

Rebalancing a channel
---------------------
The workflow for rebalancing a channel goes as follows:

* take a look at all your unbalanced channels with:

  ```$ lndmanage listchannels rebalance```
  
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

  ```$ lndmanage rebalance --max-fee-sat 20 --max-fee-rate 0.00001 channel_id```

* read the output and if everything looks well, 
  then run with the ```--reckless``` flag
* in order to increase the success probability of your rebalancing you
  can try to do it in smaller chunks, which can be set by the flag
  `--chunksize 0.5` (in this example only half the amounts are used)

Channel hygiene
---------------------
Inactive channels lock up capital, which can be used elsewhere. 
In order to close those channels it is useful to take a look
at the inactive channels with ```$ lndmanage listchannels inactive```.

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
channels with ```$lndmanage listchannels forwardings --from-days-ago 60 --sort-by='fees'```
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
Which nodes best to connect to in the Lightning Network is ongoing research. 
This also depends on your personal use case, whether you are a paying user, 
a routing node operator or a service provider (or subsets of those). Therefore
we need to empirically test, what _good nodes_ mean to us. lndmanage gives you a
few options to chose nodes from the network based on several heuristics:

* ```recommend-nodes good-old```: Based on historic forwardings of closed
channels, a list of nodes is compiled with which your node has already
had a good relationship. Due to that relationship, good interaction with that
node in the future is likely.
* ```recommend-nodes flow-analysis```: If your node has already routed
payments, you can use this information to your favor. If you want to improve
your position in the Lightning Network for routing, you may want to look for
 need of inbound liquidity. This can be achieved by estimating the 
 probability where the payments you routed were ending up. If you connect to
 those nodes directly you bypass outher routing nodes.
* ```recommend-nodes external-source```: This command lets you access text-based
lists of nodes, which are associated with economic activity. You can provide a
URL, which is parsed for node public keys and suggests nodes to connect to
(defaults to the list of [lightning networkstores](http://lightningnetworkstores.com)).
Another example of the command using 'bos-scores' is 
`$ lndmanage recommend-nodes external-source --source https://nodes.lightning.computer/availability/v1/btc.json`.
* ```recommend-nodes channel-openings```: When lightning nodes of new services
 are bootstrapped by opening a bunch of channels at the same time,
 we can detect this. Typically, a node with a large number of channel
  fluctuation signals economic activity. As the newly opened channels will 
  predominantly be of outbound type, the node will have a large
 demand for inbound liquidity, which is something you want to exploit as a
 routing node.

lndmanage supports a __channel annotation functionality__. This serves for
 remembering why a certain channel was opened. By adding the funding
transaction id or channel id to the config file `~/.lndmanage/config.ini`
under the `annotations` section (as specified in 
[`config_sample.ini`](lndmanage/templates/config_sample.ini)), annotations
can be saved. These annotations will then appear in the `listchannels` views.

Setup
-----
lndmanage will be developed in lockstep with lnd and tagged accordingly. 
If you are running an older version of lnd checkout the according 
[tag](https://github.com/bitromortac/lndmanage/releases).

Requirements: python3.6, lnd v0.7.1-beta

If you run this tool from a different host than the lnd host, 
make sure to copy `/path/to/.lnd/data/chain/bitcoin/mainnet/admin.macaroon`
 and `/path/to/.lnd/tls.cert` to your local machine, which you need for later
 configuration.

**Linux:**

You can install lndmanage via two methods:

1\. Install with pip (recommended):
```
$ python3 -m venv venv
$ source venv/bin/activate
$ python3 -m pip install lndmanage
```
2\. Install from source:
```
$ git clone https://github.com/bitromortac/lndmanage
$ cd lndmanage
$ python3 -m venv venv
$ source venv/bin/activate
$ python3 setup.py install
```

**Windows (powershell):**
Install [python3](https://www.python.org/downloads/release/python-374/),
[git](https://git-scm.com/download/win), and
 [visual studio build tools](https://visualstudio.microsoft.com/de/downloads/?q=build+tools).

You need to set the environment variable `PYTHONIOENCODING` for proper encoding to:
`$env:PYTHONIOENCODING="UTF-8"`

1\. Install with pip (recommended):
```
$ py -m venv venv
$ .\venv\Scripts\activate
$ python -m pip install lndmanage
```

2\. Install from source:
```
$ git clone https://github.com/bitromortac/lndmanage
$ cd lndmanage
$ py -m venv venv
$ .\venv\Scripts\activate
$ python setup.py install
```
**Configuration:**

When starting lndmanage for the first time, it will create a runtime folder 
`/home/user/.lndmanage`, where the configuration `config.ini` and log files
 reside. This folder location can be overwritten by setting an environment 
 variable `LNDMANAGE_HOME`. If you run this tool from a remote host to the lnd
 host, you need to configure `config.ini`.

**Running lndmanage**

The installation process created an executable `lndmanage`, which will
only be available if the created python environment is active (your prompt 
should have an `(venv)` in front):
```
$ source venv/bin/activate
```
then run
```
(venv) $ lndmanage status
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
**Due to restructuring of the project, this option is currently defunct.**

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
