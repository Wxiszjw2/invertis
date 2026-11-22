"""InvenTrack CLI — Warehouse inventory validation, deduplication, and analytics package.

Crafted by Robani Ichsan using 100% Python Standard Library.
"""

from __future__ import annotations

from typing import Final

__version__: Final[str] = "1.1.0"
__author__: Final[str] = "Robani Ichsan"
__license__: Final[str] = "MIT"

from inventrack.cli import build_parser, main
from inventrack.exceptions import (
    DataFileNotFoundError,
    InvalidDataFormatError,
    InvalidUserInputError,
    InvenTrackError,
    RecordValidationError,
    UnsupportedFormatError,
)
from inventrack.io_handler import load_inventory, save_inventory_csv, save_report_json
from inventrack.processor import (
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
