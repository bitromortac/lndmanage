#!/usr/bin/env bash

cd "$(dirname "${BASH_SOURCE[0]}")"

. _settings.sh

# we rsync repo sources to play well with docker cache
echo "Staging lndmanage source code..."
mkdir -p lndmanage/_src
rsync -a \
  --exclude='.git/' \
  --exclude='.idea/' \
  --exclude='docker/' \
  --exclude='cache/' \
  --exclude='README.md' \
  "$LNDMANAGE_SRC_DIR" \
  lndmanage/_src

echo "Building lndmanage docker container..."
exec docker-compose build "$@" lndmanage