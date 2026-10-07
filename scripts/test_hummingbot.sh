#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image_ref="hummingbot/hummingbot@sha256:d8eb5675cdd37f84f8d132b79b932f012d755d97f21e2da3fd4fef955609079d"
docker run --rm --network none --entrypoint /bin/bash \
  --workdir /repo --env PYTHONPATH=/repo:/home/hummingbot \
  --env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  --volume "$repo_dir:/repo:ro" "$image_ref" \
  -c '/opt/conda/envs/hummingbot/bin/python scripts/install_derive_v3.py --apply && /opt/conda/envs/hummingbot/bin/python scripts/hummingbot_compat.py --apply && /opt/conda/envs/hummingbot/bin/python -m pytest -q -p no:cacheprovider tests'
