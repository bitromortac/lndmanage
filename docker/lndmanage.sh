#!/usr/bin/env bash

set -e -o pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

. _settings.sh

abs_path() {
  echo "$(cd "$1"; pwd -P)"
}

if [[ ! -e "$LNDMANAGE_CACHE_DIR" ]]; then
  mkdir -p "$LNDMANAGE_CACHE_DIR"
fi
LNDMANAGE_CACHE_DIR_ABSOLUTE=$(abs_path "$LNDMANAGE_CACHE_DIR")

if [[ ! -e "$LNDMANAGE_AUX_DIR" ]]; then
  mkdir -p "$LNDMANAGE_AUX_DIR"
fi
LNDMANAGE_AUX_DIR_ABSOLUTE=$(abs_path "$LNDMANAGE_AUX_DIR")

# we use LNDMANAGE_AUX_DIR as ad-hoc volume to pass readonly.macaroon and tls.cert into our container
# it is mapped to /root/aux, config_template.ini assumes that
cp "$MACAROON_FILE" "$LNDMANAGE_AUX_DIR/readonly.macaroon"
cp "$TLS_CERT_FILE" "$LNDMANAGE_AUX_DIR/tls.cert"

if [[ -n "$LNDMANAGE_VERBOSE" ]]; then
  set -x
fi

exec docker run \
  --rm \
  --network host \
  -v "$LNDMANAGE_CACHE_DIR_ABSOLUTE:/root/.lndmanage/cache" \
  -v "$LNDMANAGE_AUX_DIR_ABSOLUTE:/root/aux" \
  -e "LND_GRPC_HOST=${LND_GRPC_HOST}" \
  -e "TLS_CERT_FILE=/root/aux/tls.cert" \
  -e "MACAROON_FILE=/root/aux/readonly.macaroon" \
  -ti \
  lndmanage:local \
  run-lndmanage "$@"
