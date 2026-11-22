"""支持通过 `python3 -m inventrack_zh` 直接运行应用。"""

import sys

from inventrack_zh.cli import main

if __name__ == "__main__":
    sys.exit(main())
