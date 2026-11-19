#!/usr/bin/env bash
# Explicitly run on the target Linux PC. Never launched by the application.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
project_root="$(pwd -P)"
if [[ "$(uname -s)" != "Linux" ]]; then
  echo 'Robotics setup requires Linux (native Ubuntu or WSL2).' >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  echo 'Install uv using its official instructions before continuing.' >&2
  exit 1
fi
mkdir -p vendor environment
if [[ ! -d vendor/lerobot ]]; then
  git clone --branch v0.6.1 --depth 1 https://github.com/huggingface/lerobot.git vendor/lerobot
fi
lerobot_commit="$(git -C vendor/lerobot rev-parse HEAD)"
lerobot_tag="$(git -C vendor/lerobot rev-parse 'v0.6.1^{commit}')"
if [[ "$lerobot_commit" != "$lerobot_tag" || "$lerobot_commit" != 7e241bd* ]]; then
  echo 'Existing vendor/lerobot is not the expected v0.6.1 checkout; it was left unchanged.' >&2
  exit 1
fi
if [[ -n "$(git -C vendor/lerobot status --porcelain --untracked-files=no)" ]]; then
  echo 'Tracked changes in vendor/lerobot must be resolved before frozen setup.' >&2
  exit 1
fi
uv sync --project vendor/lerobot --frozen --python 3.12 --extra evaluation --extra libero --extra smolvla
uv pip check --python vendor/lerobot/.venv/bin/python
PYTHONPATH="$project_root/src" vendor/lerobot/.venv/bin/python -c \
  'import json, numpy, scipy, pydantic; from failureforge.cli import parser; parser(); print(json.dumps({"application_cli_import": "passed", "numpy": numpy.__version__, "scipy": scipy.__version__, "pydantic": pydantic.__version__}, indent=2))' \
  > environment/app-contract-smoke.json
uv --version > environment/uv-version.txt
git -C vendor/lerobot rev-parse HEAD > environment/lerobot-commit.txt
sha256sum vendor/lerobot/uv.lock > environment/lerobot-lock.sha256
export MUJOCO_GL="${MUJOCO_GL:-egl}"
export LIBERO_CONFIG_PATH="${LIBERO_CONFIG_PATH:-$project_root/environment/libero-config}"
vendor/lerobot/.venv/bin/python scripts/bootstrap_robotics.py --root "$project_root"
echo 'Preparation complete. Use vendor/lerobot/.venv/bin/python for robotics commands.'
echo 'Runtime qualification and scene review are still required before live campaigns.'
