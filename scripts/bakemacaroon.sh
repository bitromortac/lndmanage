#!/bin/bash

# This command creates a macaroon containing permissions to call all the
# enpoints lndmanage uses. This is more secure than using an admin macaroon.

lncli bakemacaroon \
	--save_to lndmanage.macaroon \
        uri:/lnrpc.Lightning/GetInfo \
        uri:/lnrpc.Lightning/GetChanInfo \
        uri:/lnrpc.Lightning/GetNodeInfo \
	uri:/lnrpc.Lightning/DescribeGraph \
	uri:/lnrpc.Lightning/ListChannels \
	uri:/lnrpc.Lightning/FeeReport \
	uri:/lnrpc.Lightning/UpdateChannelPolicy \
	uri:/lnrpc.Lightning/ForwardingHistory \
	uri:/lnrpc.Lightning/ClosedChannels \
	uri:/lnrpc.Lightning/BatchOpenChannel \
	uri:/lnrpc.Lightning/ConnectPeer \
	uri:/walletrpc.WalletKit/ListUnspent \
	uri:/routerrpc.Router/QueryMissionControl
