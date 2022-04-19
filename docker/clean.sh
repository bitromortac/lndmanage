#!/usr/bin/env bash

set -e -o pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

. _settings.sh

# stop and remove all containers from lndmanage image (see https://stackoverflow.com/a/32074098/84283)
CONTAINERS=$(docker ps -a -q --filter ancestor=lndmanage --format="{{.ID}}")
if [[ -n "$CONTAINERS" ]]; then
  # shellcheck disable=SC2046
  # shellcheck disable=SC2086
  docker rm $(docker stop ${CONTAINERS})
fi

# clean volumes
rm -rf _volumes
