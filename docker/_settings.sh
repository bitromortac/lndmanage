#!/usr/bin/env bash

set -e -o pipefail

export LND_HOME=${LND_HOME:-$HOME/.lnd}
export LNDMANAGE_SRC_DIR=${LNDMANAGE_SRC_DIR:-./..}
export LNDMANAGE_CACHE_DIR=${LNDMANAGE_CACHE_DIR:-./_volumes/lndmanage-cache}

PREFERRED_SHELL=${PREFERRED_SHELL:-fish}