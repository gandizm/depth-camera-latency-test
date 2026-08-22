#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="${1:-${project_root}/build}"
cmake_args=(-S "${project_root}" -B "${build_dir}" -DCMAKE_BUILD_TYPE=Release)

if [[ -n "${RS2_PREFIX:-}" ]]; then
    cmake_args+=("-Drealsense2_DIR=${RS2_PREFIX}/lib/cmake/realsense2")
fi

cmake "${cmake_args[@]}"
cmake --build "${build_dir}" --parallel
