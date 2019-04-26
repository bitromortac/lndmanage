#!/usr/bin/env bash

cd "$(dirname "${BASH_SOURCE[0]}")"

. _settings.sh

if [[ $# -eq 0 ]]; then
  exec ./lndmanage.sh inspect ${PREFERRED_SHELL}
else
  exec ./lndmanage.sh inspect "$@"
fi
