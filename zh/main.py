"""InvenTrack CLI（简体中文版）主入口文件。"""

import sys
from pathlib import Path

ZH_ROOT = Path(__file__).resolve().parent
if str(ZH_ROOT) not in sys.path:
    sys.path.insert(0, str(ZH_ROOT))

from inventrack_zh.cli import main

if __name__ == "__main__":
    sys.exit(main())
