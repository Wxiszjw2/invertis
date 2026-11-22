"""InvenTrack CLI（简体中文版）— 基于 Python 标准库的仓库库存数据校验与补货分析工具包。

由 Robani Ichsan 设计与开发（零第三方依赖）。
"""

from __future__ import annotations

from typing import Final

__version__: Final[str] = "1.1.0"
__author__: Final[str] = "Robani Ichsan"
__license__: Final[str] = "MIT"

from inventrack_zh.cli import build_parser, main
from inventrack_zh.exceptions import (
    DataFileNotFoundError,
    InvalidDataFormatError,
    InvalidUserInputError,
    InvenTrackError,
    RecordValidationError,
    UnsupportedFormatError,
)
from inventrack_zh.io_handler import load_inventory, save_inventory_csv, save_report_json
from inventrack_zh.processor import (
    build_sku_index,
    calculate_group_recap,
    calculate_restock_recommendation,
    calculate_summary,
    classify_stock_status,
    deduplicate_records,
    enrich_records,
    extract_unique_metadata,
    filter_records,
    group_records,
    search_records,
)

__all__ = [
    "__version__",
    "__author__",
    "__license__",
    "InvenTrackError",
    "DataFileNotFoundError",
    "UnsupportedFormatError",
    "InvalidDataFormatError",
    "RecordValidationError",
    "InvalidUserInputError",
    "load_inventory",
    "save_inventory_csv",
    "save_report_json",
    "classify_stock_status",
    "calculate_restock_recommendation",
    "enrich_records",
    "deduplicate_records",
    "build_sku_index",
    "search_records",
    "filter_records",
    "group_records",
    "extract_unique_metadata",
    "calculate_group_recap",
    "calculate_summary",
    "build_parser",
    "main",
]
