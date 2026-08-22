#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
binary="${project_root}/build/rs2-latency-lab"

if [[ ! -x "${binary}" ]]; then
    echo "Missing ${binary}; run scripts/build.sh first" >&2
    exit 1
fi

if [[ -n "${RS2_PREFIX:-}" ]]; then
    export LD_LIBRARY_PATH="${RS2_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
fi

exec "${binary}" "$@"
