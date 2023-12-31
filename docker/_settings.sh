#!/usr/bin/env bash

# you have two possible ways how to specify ADMIN_MACAROON_FILE and TLS_CERT_FILE
# 1. specify LND_HOME if it is located on your local machine, we use default paths from there
# 2. specify env variables ADMIN_MACAROON_FILE and TLS_CERT_FILE

# also you want to specify LND_GRPC_HOST if your node is remote
# other config tweaks have to be done by changing lndmanage/home/config_template.ini

# note: docker uses network_mode: host

if [[ -z "$MACAROON_FILE" || -z "$TLS_CERT_FILE" ]]; then
  if [[ -z "$LND_HOME" ]]; then
    export LND_HOME="$HOME/.lnd"
    echo "warning: LND_HOME is not set, assuming '$LND_HOME'"
  fi
fi

export MACAROON_FILE=${MACAROON_FILE:-$LND_HOME/data/chain/bitcoin/mainnet/admin.macaroon}
export TLS_CERT_FILE=${TLS_CERT_FILE:-$LND_HOME/tls.cert}
export LND_GRPC_HOST=${LND_GRPC_HOST:-127.0.0.1:10009}

export LNDMANAGE_SRC_DIR=${LNDMANAGE_SRC_DIR:-./..}
export LNDMANAGE_CACHE_DIR=${LNDMANAGE_CACHE_DIR:-./_volumes/lndmanage-cache}
export LNDMANAGE_AUX_DIR=${LNDMANAGE_AUX_DIR:-./_volumes/lndmanage-aux}
export LNDMANAGE_VERBOSE=${LNDMANAGE_VERBOSE}

PREFERRED_SHELL=${PREFERRED_SHELL:-fish}
