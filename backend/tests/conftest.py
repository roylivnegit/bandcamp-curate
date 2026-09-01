import sys
from pathlib import Path

# `scripts/` (crawl.py, curate.py, co_owner_stats.py, ...) is a plain directory of
# operational scripts, not an installed package like `app` (see pyproject.toml's
# packages.find). A test that imports from it only resolves under `python -m pytest`,
# which quietly prepends the current working directory to sys.path — plain `pytest`
# (what CI and CLAUDE.md's own documented workflow both use) does not. Insert the
# backend root explicitly so `from scripts.x import y` works under either invocation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
