"""Let `python -m dsd` stand in for the console script when Scripts is not on PATH."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
