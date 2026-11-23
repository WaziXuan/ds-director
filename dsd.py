import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dsd.cli import main  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.exit(main())
