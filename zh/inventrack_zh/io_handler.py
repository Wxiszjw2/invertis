"""CSV 与 JSON 文件防御式解析与原子化导出模块。"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, Literal, TypedDict

from inventrack_zh.exceptions import (
    DataFileNotFoundError,
    InvalidDataFormatError,
    InvenTrackError,
    RecordValidationError,
    UnsupportedFormatError,
)
from inventrack_zh.validators import (
    REQUIRED_COLUMNS,
    InventoryRecord,
    RejectedRow,
    validate_and_normalize_record,
)

FileFormat = Literal["csv", "json"]


class LoadedInventory(TypedDict):
    """库存数据文件加载与校验结果。"""

    source_file: str
    format: FileFormat
    total_raw_rows: int
    records: list[InventoryRecord]
    rejected_rows: list[RejectedRow]


EXPORT_FIELDNAMES: Final[tuple[str, ...]] = (
    "sku",
    "nama_barang",
    "kategori",
    "lokasi_gudang",
    "stok",
    "stok_minimum",
    "harga_satuan",
    "nilai_stok",
    "status_stok",
    "rekomendasi_restock",
    "pemasok",
    "tanggal_update",
)


def validate_input_path(file_path: str | Path) -> Path:
    """确认输入路径存在于文件系统且为常规文件。"""
    text_path = str(file_path).strip()
    if not text_path:
        raise DataFileNotFoundError("输入文件路径不能为空。")
    path = Path(text_path)
    if not path.exists():
        raise DataFileNotFoundError(f"未找到输入文件：'{path}'。")
    if not path.is_file():
        raise DataFileNotFoundError(f"输入路径不是常规文件（可能是目录）：'{path}'。")
    return path


def detect_file_format(file_path: Path) -> FileFormat:
    """根据扩展名识别输入文件格式（.csv 或 .json）。"""
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".json":
        return "json"
    raise UnsupportedFormatError(
        f"不支持的文件格式 '{suffix or '（无扩展名）'}'，请使用 .csv 或 .json 文件。"
    )


def load_raw_csv(file_path: Path) -> list[tuple[int, dict[str, Any]]]:
    """读取 UTF-8 或 UTF-8 BOM 编码的 CSV 原始行。"""
    try:
        with file_path.open(mode="r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise InvalidDataFormatError(
                    f"CSV 文件 '{file_path}' 为空或缺少表头行。"
                )

            cleaned_fieldnames = [
                name.strip() if isinstance(name, str) else "" for name in reader.fieldnames
            ]
            reader.fieldnames = cleaned_fieldnames

            missing_columns = sorted(REQUIRED_COLUMNS - set(cleaned_fieldnames))
            if missing_columns:
                raise InvalidDataFormatError(
                    f"CSV 文件 '{file_path}' 表头不完整，缺少必填列：{', '.join(missing_columns)}。"
                )

            return [(row_num, dict(row)) for row_num, row in enumerate(reader, start=2)]
    except (UnicodeDecodeError, csv.Error, OSError) as exc:
        raise InvalidDataFormatError(f"读取 CSV 文件 '{file_path}' 失败：{exc}") from exc


def load_raw_json(file_path: Path) -> list[tuple[int, Any]]:
    """读取 JSON 文件中的原始记录列表（支持对象数组或带 'items' 键的对象）。"""
    try:
        with file_path.open(mode="r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise InvalidDataFormatError(f"解析 JSON 文件 '{file_path}' 失败：{exc}") from exc

    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
    else:
        raise InvalidDataFormatError(
            f"JSON 文件 '{file_path}' 根节点必须为对象数组 [...] 或包含列表类型 'items' 键的对象。"
        )

    return [(index, item) for index, item in enumerate(items, start=1)]


def load_inventory(file_path: str | Path, *, strict: bool = False) -> LoadedInventory:
    """从 CSV 或 JSON 文件加载并校验全部库存数据。"""
    path = validate_input_path(file_path)
    file_format = detect_file_format(path)
    raw_rows = load_raw_csv(path) if file_format == "csv" else load_raw_json(path)

    valid_records: list[InventoryRecord] = []
    rejected_rows: list[RejectedRow] = []

    for row_number, raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            rejected_rows.append(
                {
                    "row_number": row_number,
                    "sku": "-",
                    "reason": (
                        f"第 {row_number} 行：JSON 元素必须为对象，实际收到 {type(raw_row).__name__}。"
                    ),
                }
            )
            continue

        if None in raw_row:
            rejected_rows.append(
                {
                    "row_number": row_number,
                    "sku": str(raw_row.get("sku") or "-").strip() or "-",
                    "reason": f"第 {row_number} 行：列数超出 CSV 表头定义。",
                }
            )
            continue

        try:
            normalized = validate_and_normalize_record(raw_row, row_number)
            valid_records.append(normalized)
        except RecordValidationError as exc:
            raw_sku = str(raw_row.get("sku") or "-").strip() or "-"
            rejected_rows.append(
                {
                    "row_number": row_number,
                    "sku": raw_sku,
                    "reason": str(exc),
                }
            )

    if strict and rejected_rows:
        first_reason = rejected_rows[0]["reason"]
        raise InvalidDataFormatError(
            f"严格模式校验失败：共发现 {len(rejected_rows)} 条无效记录。首条错误 -> {first_reason}"
        )

    return {
        "source_file": str(path),
        "format": file_format,
        "total_raw_rows": len(raw_rows),
        "records": valid_records,
        "rejected_rows": rejected_rows,
    }


def save_inventory_csv(records: Sequence[dict[str, Any]], output_path: str | Path) -> Path:
    """以原子替换方式将库存记录列表保存为标准 UTF-8 CSV 文件。"""
    destination = Path(output_path)
    temp_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=destination.parent,
            prefix=f".{destination.stem}_",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            temp_path = Path(tmp_file.name)
            writer = csv.DictWriter(
                tmp_file,
                fieldnames=list(EXPORT_FIELDNAMES),
                extrasaction="ignore",
            )
            writer.writeheader()
            for record in records:
                row_to_write = {field: record.get(field, "") for field in EXPORT_FIELDNAMES}
                writer.writerow(row_to_write)
        os.replace(temp_path, destination)
    except OSError as exc:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise InvenTrackError(f"保存 CSV 文件至 '{destination}' 失败：{exc}") from exc
    return destination


def save_report_json(report: dict[str, Any], output_path: str | Path) -> Path:
    """以原子替换方式将分析报告保存为 UTF-8 JSON 文件。"""
    destination = Path(output_path)
    temp_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.stem}_",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            temp_path = Path(tmp_file.name)
            json.dump(report, tmp_file, indent=2, ensure_ascii=False)
            tmp_file.write("\n")
        os.replace(temp_path, destination)
    except (OSError, TypeError, ValueError) as exc:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise InvenTrackError(f"保存 JSON 报告至 '{destination}' 失败：{exc}") from exc
    return destination
