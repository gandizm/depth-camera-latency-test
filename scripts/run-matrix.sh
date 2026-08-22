#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runner="${project_root}/scripts/run.sh"
result_dir="${RESULT_DIR:-${project_root}/results/$(date +%Y%m%d-%H%M%S)}"
repeats="${REPEATS:-3}"
duration="${DURATION:-60}"
warmup="${WARMUP:-10}"
rotation="${ROTATE:-0}"
only=",${ONLY:-},"
serial_args=()

if [[ -n "${SERIAL:-}" ]]; then
    serial_args=(--serial "${SERIAL}")
fi

mkdir -p "${result_dir}"

matrix=(
    "rgb-vga-30|--stream color --width 640 --height 480 --fps 30 --format yuyv --no-depth"
    "rgb-vga-60|--stream color --width 640 --height 480 --fps 60 --format yuyv --no-depth"
    "rgb-qvga-60|--stream color --width 320 --height 240 --fps 60 --format yuyv --no-depth"
    "rgb-1080p-30|--stream color --width 1920 --height 1080 --fps 30 --format yuyv --no-depth"
    "rgb-vga-30-depth|--stream color --width 640 --height 480 --fps 30 --format yuyv --with-depth --depth-width 640 --depth-height 480 --depth-fps 30"
    "rgb-vga-60-depth|--stream color --width 640 --height 480 --fps 60 --format yuyv --with-depth --depth-width 640 --depth-height 480 --depth-fps 60"
    "rgb-qvga-60-depth|--stream color --width 320 --height 240 --fps 60 --format yuyv --with-depth --depth-width 640 --depth-height 480 --depth-fps 60"
    "rgb-1080p-30-depth|--stream color --width 1920 --height 1080 --fps 30 --format yuyv --with-depth --depth-width 640 --depth-height 480 --depth-fps 30"
    "rgb-vga-60-depth-vga-90|--stream color --width 640 --height 480 --fps 60 --format yuyv --with-depth --depth-width 640 --depth-height 480 --depth-fps 90"
    "rgb-vga-60-depth-qvga-90|--stream color --width 640 --height 480 --fps 60 --format yuyv --with-depth --depth-width 320 --depth-height 240 --depth-fps 90"
)

echo "Results: ${result_dir}"
echo "Keep the selected camera fixed on the full circle row for every run."

for repeat in $(seq 1 "${repeats}"); do
    for entry in "${matrix[@]}"; do
        label="${entry%%|*}"
        if [[ "${only}" != ",," && "${only}" != *",${label},"* ]]; then
            continue
        fi
        argument_text="${entry#*|}"
        read -r -a profile_args <<<"${argument_text}"
        stem="${label}-r${repeat}"
        echo "RUN ${stem}"
        "${runner}" "${serial_args[@]}" "${profile_args[@]}" \
            --rotate "${rotation}" --duration "${duration}" \
            --warmup "${warmup}" \
            --csv "${result_dir}/${stem}.csv" \
            2>&1 | tee "${result_dir}/${stem}.log"
    done
done

summary_status=0
python3 "${project_root}/scripts/summarize.py" "${result_dir}" \
    --markdown "${result_dir}/summary.md" \
    --csv "${result_dir}/summary.csv" \
    --fail-on-empty || summary_status=$?

echo "Summary: ${result_dir}/summary.md"
if (( summary_status != 0 )); then
    echo "Matrix is incomplete: realign the camera and rerun every zero-sample group." >&2
    exit "${summary_status}"
fi
