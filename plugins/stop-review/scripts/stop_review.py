"""Run the plugin's bundled package from its installed location."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stop_review.cli import main

raise SystemExit(main())
