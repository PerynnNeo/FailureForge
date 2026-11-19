#!/usr/bin/env bash
# Start the local application and, when qualified, the real sequential worker.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
root="$(pwd -P)"
data_dir="${FAILUREFORGE_DATA_DIR:-$root/data/workbench}"
app_python="$root/.venv/bin/python"
robot_python="$root/vendor/lerobot/.venv/bin/python"
export PYTHONPATH="$root/src"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}" LP_NUM_THREADS="${LP_NUM_THREADS:-8}"
if [[ ! -x "$app_python" || ! -s "$root/apps/web/dist/index.html" ]]; then
  echo "Prepare the application Python environment and build apps/web before starting." >&2
  exit 1
fi
api_pid=
worker_pid=
cleanup() {
  if [[ -n "$api_pid" ]]; then kill "$api_pid" 2>/dev/null || true; fi
  if [[ -n "$worker_pid" ]]; then kill "$worker_pid" 2>/dev/null || true; fi
  wait || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$app_python" -m failureforge --data-dir "$data_dir" serve --host 127.0.0.1 --port "${FAILUREFORGE_PORT:-8000}" &
api_pid=$!
report="$data_dir/qualification/qualification.json"
if [[ -x "$robot_python" && -f "$report" ]] && renderer="$("$app_python" -c '
import json, sys
with open(sys.argv[1]) as stream:
    record = json.load(stream)
if not (record.get("qualified") and record.get("scene_review_approved")):
    sys.exit(1)
print(record["environment"]["renderer"])
' "$report")"; then
  "$robot_python" -m failureforge --data-dir "$data_dir" worker --backend libero \
    --model-path "$root/models/smolvla_libero" --renderer "$renderer" --episode-timeout 600 &
  worker_pid=$!
  wait -n "$api_pid" "$worker_pid"
else
  echo "Starting project analyses and evidence browsing. The robot worker needs an approved qualification."
  wait "$api_pid"
fi
