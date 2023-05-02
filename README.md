<p align="center">
<img src="https://github.com/bitromortac/lndmanage/raw/master/logo.png" style="max-width:100%;" width="400" />
</p>

[![Build]][build_url]
[![Version]][build_url]
[![Size]][hub_url]
[![Pulls]][hub_url]

[build_url]: https://github.com/kroese/lndmanage/actions
[hub_url]: https://hub.docker.com/r/kroese/lndmanage

[Build]: https://github.com/kroese/lndmanage/actions/workflows/build.yml/badge.svg
[Size]: https://img.shields.io/docker/image-size/kroese/lndmanage/latest?color=066da5&label=size
[Pulls]: https://img.shields.io/docker/pulls/kroese/lndmanage.svg?style=flat&label=pulls&logo=docker
[Version]: https://img.shields.io/docker/v/kroese/lndmanage?arch=amd64&sort=date&color=066da5

<hr />

# lndmanage
lndmanage is a command line tool for advanced channel management of an 
[LND](https://github.com/lightningnetwork/lnd) node.

**DISCLAIMER: This is BETA software, so please be careful. No warranty is given.**

[See installation instructions.](#setup)

### Feature list:

* Activity reports [```report```](#activity-report)
* Display the node summary ```status```
* [```info```](#info-command) command: explore info about a channel or node in the graph
* Advanced channel listings ```listchannels```
  * ```listchannels rebalance```: list channels for rebalancing
  * [```listchannels forwardings```](#forwarding-information): list forwarding statistics for each channel 
  * [```listchannels hygiene```](#active-channels): information for closing of active channels
  * [```listchannels inactive```](#inactive-channels): information on inactive channels
* Peer listing [```listpeers```](#peer-listing): aggregated channel statistics
* Fee updating [```update-fees```](#fee-optimization): increase revenue and rebalance by fee optimization
* Recommendation of good nodes [```recommend-nodes```](#channel-opening-strategies)
* Batched channel opening [```openchannels```](#batched-channel-opening)
* Support of [```lncli```](#lncli-support)
   
## Command Line Options
```
usage: lndmanage.py [-h] [--loglevel {INFO,DEBUG}] {status,listchannels,recommend-nodes,report,info,lncli,openchannels,update-fees} ...

Lightning network daemon channel management tool.

positional arguments:
  {status,listchannels,recommend-nodes,report,info,lncli,openchannels,update-fees}
    status              display node status
    listchannels        lists channels with extended information [see also subcommands with -h]
    listpeers           lists peers with extended information
    recommend-nodes     recommends nodes [see also subcommands with -h]
    report              displays reports of activity on the node
    info                displays info on channels and nodes
    lncli               execute lncli
    openchannels        opens multiple channels
    update-fees         optimize the fees on your channels to increase revenue and to automatically rebalance
```

## Info Command
Sometimes it is necessary to get more information about a specific public channel
or node. This could be for example trying to figure out what fees are typically
charged by a node or to look up its IP address.

With the info command you can enter

`$ lndmanage info CHANNEL_ID`

or

`$ lndmanage info NODE_PUBLIC_KEY`

and it will automatically detect whether you are asking for a channel or node info.

Sample output for a channel:
```
-------- Channel info --------
channel id: CHANIDXXXXXXXXXXXX  channel point: CHANPOINTXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX:X
          capacity:                 500000 sat                                                                                      
          blockheight:              606273                                                                                          
          open since:               2019-10-07 13:31:24                                                                             
          channel age:              139.030000 days                                                                                  
          last update:              2020-02-25 06:15:09                                                                             

-------- Channel partners --------
NODEPUBKEYXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX | NODEPUBKEYXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
                       ALIAS 1                                     |                       ALIAS 2
          base fee:                 1000 msat                      |           base fee:                 1000 msat                       
          fee rate:                 0.000001 sat/sat               |           fee rate:                 0.002500 sat/sat              
          time lock delta:          40 blocks                      |           time lock delta:          14 blocks                     
          disabled:                 False                          |           disabled:                 False                         
          last update:              2020-01-20 13:12:09            |           last update:              2020-01-22 10:28:57
```

Sample output for a node:
```
-------- Node info --------
NODEPUBKEYXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
          alias:                    ALIAS                                                                                           
          last update:              2020-02-24 16:45:09                                                                             
          number of channels:       44                                                                                              
          total capacity:           33333333 sat                                                                                    
          capacity (median):        150000 sat                                                                                      
          capacity (mean):          500000 sat                                                                                      
          base fee (median):        1000 msat                                                                                       
          base fee (mean):          666 msat                                                                                        
          fee rate (median):        0.000001 sat/sat                                                                                
          fee rate (mean):          0.002039 sat/sat                                                                                
-------- Addresses --------
     NODEPUBKEYXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX@XX.XXX.XXX.XXX:9735
```

## Activity Report
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

## Forwarding Information
A more sophisticated way to see if funds have to be reallocated is to 
have a look at the forwarding statistics of, e.g., the last two months
 of the individual channels with 
 ```$ lndmanage listchannels forwardings --from-days-ago 60 --sort-by='fees'```
 (here sorted by total fees, but it can be sorted by any column field).

The output will look like:
```
-------- Description --------
cid        channel id
nfwd       number of forwardings
age        channel age [days]
fees       total fees [sat]
f/w        total fees per week [sat / week]
flow       flow direction (positive is outwards)
ub         unbalancedness [-1 ... 1] (0 is 50:50 balanced)
bwd        bandwidth demand: capacity / max(mean_in, mean_out)
r          action is required
cap        channel capacity [sat]
pbf        peer base fee [msat]
pfr        peer fee rate
annotation channel annotation
alias      alias
-------- Channels --------
       cid         nfwd   age  fees     f/w  flow    ub  bwd r     cap  pbf      pfr  alias
xxxxxxxxxxxxxxxxxx    6   103   907 106.950  1.00  0.30 0.00 X 6000000  231 0.000006    abc
xxxxxxxxxxxxxxxxxx    3    82   300  35.374 -0.08  0.74 0.70   1000000 1000 0.000001    def
xxxxxxxxxxxxxxxxxx    4    32   216  25.461  0.42  0.38 0.17 X 6000000 1003 0.000003    ghi
...
```

## Fee Optimization
The `update-fees` command lets you dynamically update the fee rates and base fees on your
channels. It analyzes the outward (fee-earning) forwardings that happened on them and lowers
or increases fees incrementally based on the demand. The minimal and maximal fee rate boundaries
are configurable (see `update-fees -h`). The fee optimization will enforce that fee rates
are not lowered, when the channel has no outbound liquidity, it economically enforces a
buffer for excess demand times.

The command will not set new fees unless the user answers with `yes` after the statistics output.

Example output for a channel with excess demand:
```
>>> Fee optimization for node XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX (node alias):
    Channels with peer: 1, total capacity: 5000000, total local balance: 1033113
    Outward forwarded amount: 1521253 (rate 217322 / target rate 14286)
    Number of outward forwardings:      1
    Fee rate change: 0.000150 -> 0.000225 (factor 1.500)
    Base fee change:    0 ->    0 (factor 0.750)
  > Statistics for channel XXXXXXXXXXXXXXXXXX:
    ub: 0.59, flow: 0.26, fees: 226.666 sat, cap: 5000000 sat, lb: 1033113 sat, nfwd: 2, in: 895518 sat, out: 1521253 sat.
```
One can see that the channel routed more than the target of 14286 sat/day, so the fee rate is increased by a factor of 1.5.

Example output for a channel with no demand:
```
>>> Fee optimization for node XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX (node alias):
    Channels with peer: 1, total capacity: 5000000, total local balance: 3134892
    Outward forwarded amount:      0 (rate     0 / target rate 14286)
    Number of outward forwardings:      0
    Fee rate change: 0.000149 -> 0.000106 (factor 0.707)
    Base fee change:    0 ->    0 (factor 0.750)
  > Statistics for channel XXXXXXXXXXXXXXXXXX:
    ub: -0.25, flow: 0.00, fees: 0.000 sat, cap: 5000000 sat, lb: 3134892 sat, nfwd: 0, in: 0 sat, out: 0 sat.
```
There was no demand on that channel, so the fee rate was decreased by a factor of 0.707.

Example for an exhausted channel:
```
>>> Fee optimization for node XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX (node alias)
    Channels with peer: 1, total capacity: 2000000, total local balance: 20810
    Outward forwarded amount:      0 (rate     0 / target rate 14286)
    Number of outward forwardings:      0
    Fee rate change: 0.000150 -> 0.000157 (factor 1.048)
    Base fee change:    0 ->    0 (factor 0.750)
  > Statistics for channel XXXXXXXXXXXXXXXXXX:
    ub: 0.98, flow: 0.00, fees: 0.000 sat, cap: 2000000 sat, lb: 20810 sat, nfwd: 0, in: 0 sat, out: 0 sat.
```
This channel is exhausted (it only has 20810 sat left in it, or ub=0.98). Even though
there was no demand for this channel, the fee rate is *not* lowered, but kept roughly
constant (increased a bit by factor 1.048) in the hope it will be filled again by an
incoming forwarding event.

The target for how much a channel should route per day can be set via the
`--target-forwarding-amount-sat` config parameter. This value has direct influence on
the revenue, but it is unknown beforehand and every node operator has to tune it.
A reasonable value could be half of the daily routed amount of the best-income
channel (see `lndmanage listchannels forwardings`). Future work will focus on setting
the target amount automatically on a per channel basis. After each optimization step
forwarding statistics are collected in a json file, to use the data in the future to
model the fee-demand curve. *Please report if the default parameter is way too off for you.*

Channels can be exempt from fee updates via the `[excluded-channels-fee-opt]` config
section, see [config example](lndmanage/templates/config_sample.ini).

The `update-fees` command is meant to be run periodically. A weekly interval is
recommended to not put too much strain on the network, which also averages out weekly
patterns and makes the gossip propagate also to nodes that are not always
online like mobile phones.

A convenient way to run this command automatically (every Sunday) is via a cronjob:
```
$ crontab -e
# m h  dom mon dow   command
0 0 * * Sun lndmanage update-fees --reckless --from-days-ago 7
```

### Initial fee setting
If a node was bootstrapped or one is unsure which initial fees to apply, it is
recommended to apply high inital fee rates. This can be accomplished by
`$ lndmanage update-fees --init`. If the node has done already some forwardings,
one can immediately follow with a `$ lndmanage update-fees --from-days-ago 30` and
the fees will adjust downwards or upwards depending on the historic traffic. In order
for opened channels to not start with a very low fee setting (and thus to prevent
immediate depletion), it is recommended to set a default high fee rate for channel
opening in the lnd config:
```
bitcoin.feerate=2500
```


## Channel hygiene
### Inactive Channels
Inactive channels ([Zombie channels](https://medium.com/@gcomxx/get-rid-of-those-zombie-channels-1267d5a2a708))
 lock up capital, which can be used elsewhere. 
In order to close those channels it is useful to take a look
at the inactive channels with ```$ lndmanage listchannels inactive```.

You will get an output like:

```
-------- Description --------
cid        channel id
lupp       last update time by peer [days ago]
priv       channel is private
ini        true if we opened channel
age        channel age [days]
ub         unbalancedness [-1 ... 1] (0 is 50:50 balanced)
cap        channel capacity [sat]
lb         local balance [sat]
rb         remote balance [sat]
sr/w       sent and received per week [sat]
annotation channel annotation
alias      alias

-------- Channels --------
cid                lupp priv ini age    ub     cap    lb   rb sr/w alias
xxxxxxxxxxxxxxxxxx   66  ✗   ✓   71  0.03 2000000 10000  100    0   abc
xxxxxxxxxxxxxxxxxx   20  ✗   ✗  113 -0.23   40000     0    0    0   def
xxxxxxxxxxxxxxxxxx   19  ✓   ✗   21  1.00 1200000  1000    0    0   ghi
...
```
Channels, which were updated a long time ago (```lupp```) are likely to be 
inactive in the future and may be closed. Be aware, that if you are the initiator
of the channel, you have to pay a hefty fee for the force closing.

### Active Channels
As well as inactive channels, active channels can lock up capital that is
better directed towards other nodes. In order to facilitate the hard
decision whether a channel should be closed, one can have a look at the
`$ lndmanage listchannels hygiene` command output, which will display relevant
 data of the last 60 days:
```
-------- Description --------
cid        channel id
age        channel age [days]
nfwd       number of forwardings
f/w        total fees per week [sat / week]
ulr        ratio of uptime to lifetime of channel [0 ... 1]
lb         local balance [sat]
cap        channel capacity [sat]
pbf        peer base fee [msat]
pfr        peer fee rate
annotation channel annotation
alias      alias
-------- Channels --------
       cid           age  nfwd    f/w   ulr        lb       cap   pbf      pfr alias           
xxxxxxxxxxxxxxxxxx   315     0   0.00  0.20       100     91000  1000 0.000001 abc 
xxxxxxxxxxxxxxxxxx   221     0   0.00  0.80         0    400000  1000 0.000001 def 
xxxxxxxxxxxxxxxxxx    36     0   0.00  0.99         0    200000  1000 0.000001 ghi 
xxxxxxxxxxxxxxxxxx    24     5   0.20  1.00    100000   4000000   500 0.000001 jkl 
xxxxxxxxxxxxxxxxxx   117    10   1.10  1.00     30000    500000  1000 0.000001 mno
```
You can base your decision on the number of forwardings `nfwd` and the fees
collected per week `f/w`. If those numbers are low and the local balance `lb`
is high and the channel already had enough time (`age`) to prove itself, you
may want to consider closing the channel. Another way to judge the reliability
of the channel is to look at the proportion the channel stayed active when
your node was active, given by the `ulr` column.

## Peer listing
The command `$ lndmanage listpeers` will show aggregated statistics for channels. This
is important if one has for example a public channel (for route advertisement), but
other channels are kept private. Care must be taken that always at least a single channel
is public, which is indicated by the `maximum public channel capacity`. `listpeers` shows
statistics  such as total incoming and outgoing forwarding amounts as well as total local
and remote balance. Subcommands `listpeers in` or `listpeers out` can be used to sort by
incoming or outgoing traffic.

## Channel Opening Strategies
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
 those nodes directly you bypass other routing nodes.
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
* ```recommend-nodes second-neighbors```: One way of improving the position of the node
in the network is to get connected to as many as possible other nodes
with a least number of additional hops. With the `second-neighbors` command
you can get a list of nodes that would give you the most new second neighbors,
 if you would open up a channel with.

lndmanage supports a __channel annotation functionality__. This serves for
 remembering why a certain channel was opened. By adding the funding
transaction id or channel id to the config file `~/.lndmanage/config.ini`
under the `annotations` section (as specified in 
[`config_sample.ini`](lndmanage/templates/config_sample.ini)), annotations
can be saved. These annotations will then appear in the `listchannels` views.

## Batched Channel Opening
lndmanage supports batched channel opening wrapping LND's batchopen command. With this 
command you can specify node pubkeys, amounts or a total amount for your channels.

## Support of lncli
lndmanage supports the native command line interface of `lnd` in interactive mode.
This achieves the goal of having to only open one terminal window for node
management and enables an easy way to run `lncli` from remote machines. In
interactive mode `lncli` is available as it would be via command line, e.g.:

`$ lndmangage lncli getinfo`

The json text output you get from `lncli` is syntax highlighted. To enable
`lncli` support, lndmanage needs to find the `lncli` executable on the path, or
in the `~/.lndmanage` home folder (or environment variable `LNDMANAGE_HOME`).
To get the `lncli` binary, copy it over from your `$GOPATH/bin/lncli`, compile it
yourself, or download one of the official [releases](https://github.com/lightningnetwork/lnd/releases).
*If lndmanage runs on the same host as `lnd` you typically don't have to do
anything.* To check if it's working you should see
`Enabled lncli: using /path/to/lncli` and be able to access the `lncli` option.

## Setup
lndmanage will be developed in lockstep with lnd and tagged accordingly. 
If you are running an older version of lnd checkout the according 
[tag](https://github.com/bitromortac/lndmanage/releases).

### Requirements
Installation of lndmanage requires `>=python3.8`, `lnd v0.14.x`, `python3-venv`.

#### Optional Requirements
Depending on if you want to install from source dependency packages you may
need `gcc`, `g++`, `python3-dev(el)`.

#### LND Build Requirements
Some commands will only work correctly if lnd is built with the `routerrpc`.
This can be done when compiling with minimal build tags of `make && make install 
tags="routerrpc signrpc walletrpc"`. If you use precompiled binaries, you can 
ignore this.

#### Admin Macaroon and TLS cert needed
If you run this tool from a different host than the lnd host, 
make sure to copy `/path/to/.lnd/data/chain/bitcoin/mainnet/admin.macaroon`
 and `/path/to/.lnd/tls.cert` to your local machine, which you need for later
 configuration.

### Linux

You can install lndmanage via two methods:

1\. Install with pip (recommended):
```
$ python3 -m venv venv
$ source venv/bin/activate
$ pip install --upgrade pip setuptools wheel
$ python3 -m pip install lndmanage
```
2\. Install from source:
```
$ git clone https://github.com/bitromortac/lndmanage
$ cd lndmanage
$ python3 -m venv venv
$ source venv/bin/activate
$ pip install --upgrade pip setuptools wheel
$ pip install .
```

### Windows (powershell)
Install [python3](https://www.python.org/downloads/release/python-374/),
[git](https://git-scm.com/download/win), and
 [visual studio build tools](https://visualstudio.microsoft.com/en/downloads/?q=build+tools).

You need to set the environment variable `PYTHONIOENCODING` for proper encoding to:
`$env:PYTHONIOENCODING="UTF-8"`

1\. Install with pip (recommended):
```
$ py -m venv venv
$ .\venv\Scripts\activate
$ pip install --upgrade pip setuptools wheel
$ python -m pip install lndmanage
```

2\. Install from source:
```
$ git clone https://github.com/bitromortac/lndmanage
$ cd lndmanage
$ py -m venv venv
$ .\venv\Scripts\activate
$ pip install --upgrade pip setuptools wheel
$ pip install .
```
### Configuration

When starting lndmanage for the first time, it will create a runtime folder 
`/home/user/.lndmanage`, where the configuration `config.ini` and log files
 reside. This folder location can be overwritten by setting an environment 
 variable `LNDMANAGE_HOME`. If you run this tool from a remote host to the lnd
 host, you need to configure `config.ini`.

### Running lndmanage

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

**Running lndmanage interactively (recommended)**

lndmanage supports an interactive mode with command history. The interactive
mode has the advantage that the network graph has to be read into memory only
once, giving a much faster execution time for subsequent command invocations.

Interactive mode is started by calling lndmanage without arguments:
```bash
$ lndmanage
Running in interactive mode. You can type 'help' or 'exit'.
$ lndmanage listchannels forwardings
<output>
$ lndmanage exit
```
Commands that can be entered are the ones you would give as arguments.

## Testing
Requirements are an installation of [lnregtest](https://github.com/bitromortac/lnregtest)
and links to bitcoind, bitcoin-cli, lnd, and lncli in the `test/bin` folder.

Tests can be run with
`python3 -m unittest discover test`
from the root folder.

## gRPC Reproducibility
Note that this repository ships prebuilt gRPC interfaces to communicate with LND.
These libraries (located in `lndmanage/grpc_compiled`) contain code that is hard
to review and should not be trusted. In order to check that the libraries indeed
can be reproduced from the LND repository, one can run the `build_grpc.sh`
script and observe differences via git.

## Docker

If you prefer to run `lndmanage` from a docker container, `cd docker` 
and follow the [`README`](docker/README.md) there.
