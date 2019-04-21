#!/usr/bin/env bash

cd "$(dirname "${BASH_SOURCE[0]}")"

. _settings.sh

CONTAINER_ID=$(docker-compose ps -q lndmanage)
if [[ -z $(docker ps -q --no-trunc | grep "$CONTAINER_ID") ]]; then
  exec ./dc run --rm lndmanage ${PREFERRED_SHELL}
else
  exec ./dc exec lndmanage ${PREFERRED_SHELL}
fi