"""Keep repository-local imports stable when pytest is launched from any cwd."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# The controller ships only inside the Condor agent folder; Hummingbot imports it
# as a single module, so tests import it the same way: `import derive_cesf_long_vol`.
CONTROLLER_DIR = ROOT / "condor/flyby/controllers/derive_cesf_long_vol"
for path in (str(ROOT), str(CONTROLLER_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)
