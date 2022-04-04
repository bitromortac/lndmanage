#!/usr/bin/env bash

set -e -o pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

. _settings.sh

echo "Building lndmanage docker container..."
if [[ -n "$LNDMANAGE_VERBOSE" ]]; then
  set -x
fi
exec docker build \
  --build-arg LNDMANAGE_HOST_SRC_PATH="${LNDMANAGE_HOST_SRC_PATH:-.}" \
  -t lndmanage:local \
  -f ./lndmanage/Dockerfile \
  "$@" \
  ..
