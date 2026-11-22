"""Memungkinkan package dijalankan langsung dengan `python3 -m inventrack`."""

import sys

from inventrack.cli import main

if __name__ == "__main__":
    sys.exit(main())
