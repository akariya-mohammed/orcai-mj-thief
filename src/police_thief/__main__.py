"""Entry point for `python -m police_thief` and the `police-thief` console script."""
import sys

from police_thief.cli import main

if __name__ == "__main__":
    sys.exit(main())
