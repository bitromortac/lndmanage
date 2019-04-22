#!/usr/bin/env bash

cd "$(dirname "${BASH_SOURCE[0]}")"

. _settings.sh

CONTAINER_ID=$(docker-compose ps -q lndmanage)
if [[ -z $(docker ps -q --no-trunc | grep "$CONTAINER_ID") ]]; then
  exec docker-compose run --rm lndmanage run-lndmanage "$@"
else
  exec docker-compose exec lndmanage run-lndmanage "$@"
fi