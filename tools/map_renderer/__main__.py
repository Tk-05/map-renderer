"""Entry point for `python -m map_renderer` and `python tools/map_renderer`."""

import sys
from pathlib import Path

if not __package__:
    # Started as `python tools/map_renderer`: make the package importable.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from map_renderer.cli import main
else:
    from .cli import main

if __name__ == "__main__":
    sys.exit(main())
