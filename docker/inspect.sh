#!/usr/bin/env bash

cd "$(dirname "${BASH_SOURCE[0]}")"

. _settings.sh

CMD=${1:-run}

exec docker ${CMD} -ti lndmanage ${PREFERRED_SHELL}
