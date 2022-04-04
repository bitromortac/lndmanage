#!/usr/bin/env bash

set -e -o pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "Building lndmanage docker container..."
if [[ -n "$LNDMANAGE_VERBOSE" ]]; then
  set -x
fi
exec docker build \
  --build-arg LNDMANAGE_HOST_SRC_PATH="${LNDMANAGE_HOST_SRC_PATH:-.}" \
  --build-arg LNDMANAGE_EXTRA_PACKAGES="${LNDMANAGE_EXTRA_PACKAGES:-fish}" \
  -t lndmanage:local \
  -f ./Dockerfile \
  "$@" \
  ..
