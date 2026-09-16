"""Launch the Mouthpiece tray (double-click, or via Mouthpiece.cmd for the venv interpreter)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mouthpiece.tray import main  # noqa: E402

sys.exit(main())
