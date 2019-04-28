#!/usr/bin/env bash

cd "$(dirname "${BASH_SOURCE[0]}")"

. _settings.sh

if [[ $# -eq 0 ]]; then
  set -- ${PREFERRED_SHELL}
fi

exec ./lndmanage.sh inspect "$@"
