"""库存记录类型定义、常量约束与字段规范化校验模块。"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Final, Literal, TypedDict

from inventrack_zh.exceptions import RecordValidationError

StockStatusZh = Literal["缺货", "预警", "正常", "积压"]
DedupStrategy = Literal["latest", "first"]
GroupField = Literal["kategori", "lokasi_gudang", "status_stok", "pemasok"]


class InventoryRecord(TypedDict):
    """通过校验与规范化后的单条库存记录字典结构。"""

    sku: str
    nama_barang: str
    kategori: str
    lokasi_gudang: str
    stok: int
    stok_minimum: int
    harga_satuan: float
    pemasok: str
    tanggal_update: str


class EnrichedRecordZh(InventoryRecord):
    """包含衍生估值、状态与建议补货量的库存记录结构。"""

    nilai_stok: float
    status_stok: StockStatusZh
    rekomendasi_restock: int


class RejectedRow(TypedDict):
    """防御式解析阶段隔离的无效行审计条目。"""

    row_number: int
    sku: str
    reason: str


class DuplicateEntry(TypedDict):
    """重复 SKU 去重处理审计记录。"""

    sku: str
    strategy: str
    kept_tanggal: str
    discarded_tanggal: str
    discarded_nama: str
    reason: str


REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "sku",
        "nama_barang",
        "kategori",
        "lokasi_gudang",
        "stok",
        "stok_minimum",
        "harga_satuan",
        "pemasok",
        "tanggal_update",
    }
)
VALID_STATUSES: Final[frozenset[str]] = frozenset({"缺货", "预警", "正常", "积压"})
VALID_DEDUP_STRATEGIES: Final[frozenset[str]] = frozenset({"latest", "first"})
VALID_GROUP_FIELDS: Final[frozenset[str]] = frozenset(
    {"kategori", "lokasi_gudang", "status_stok", "pemasok"}
)


def normalize_sku(raw_sku: Any) -> str:
    """规范化 SKU 编码：去除首尾与多余空白并转为全大写。"""
    if raw_sku is None or isinstance(raw_sku, (bool, dict, list)):
        raise ValueError("字段 'sku' 必须为有效文本。")
    cleaned = " ".join(str(raw_sku).split()).upper()
    if not cleaned:
        raise ValueError("字段 'sku' 不能为空。")
    return cleaned


def normalize_text(
    raw_value: Any,
    field_name: str,
    *,
    title_case: bool = False,
    upper_case: bool = False,
) -> str:
    """清理文本中的多余空白并验证非空。"""
    if raw_value is None or isinstance(raw_value, (bool, dict, list)):
        raise ValueError(f"字段 '{field_name}' 必须为有效文本。")
    cleaned = " ".join(str(raw_value).split())
    if not cleaned:
        raise ValueError(f"字段 '{field_name}' 不能为空。")
    if upper_case:
        return cleaned.upper()
    if title_case:
        return cleaned.title()
    return cleaned


def parse_non_negative_int(raw_value: Any, field_name: str) -> int:
    """解析并校验非负整数（>= 0），拒绝布尔值、小数、非有限值及负数。"""
    if raw_value is None or isinstance(raw_value, (bool, dict, list)):
        raise ValueError(f"字段 '{field_name}' 必须为非负整数。")
    if isinstance(raw_value, int):
        parsed = raw_value
    elif isinstance(raw_value, float):
        if not math.isfinite(raw_value) or not raw_value.is_integer():
            raise ValueError(
                f"字段 '{field_name}' 不接受小数或非有限数值（收到 {raw_value}）。"
            )
        parsed = int(raw_value)
    else:
        text = str(raw_value).strip()
        if not text:
            raise ValueError(f"字段 '{field_name}' 不能为空。")
        try:
            parsed = int(text)
        except ValueError as exc:
            raise ValueError(
                f"字段 '{field_name}' 必须是不含小数的整数，当前收到 '{raw_value}'。"
            ) from exc

    if parsed < 0:
        raise ValueError(f"字段 '{field_name}' 不能为负数（{parsed}）。")
    return parsed


def parse_non_negative_float(raw_value: Any, field_name: str) -> float:
    """解析并校验有限非负浮点数（>= 0），保留两位小数。"""
    if raw_value is None or isinstance(raw_value, (bool, dict, list)):
        raise ValueError(f"字段 '{field_name}' 必须为非负数值。")
    if isinstance(raw_value, (int, float)):
        parsed = float(raw_value)
    else:
        text = str(raw_value).strip()
        if not text:
            raise ValueError(f"字段 '{field_name}' 不能为空。")
        try:
            parsed = float(text)
        except ValueError as exc:
            raise ValueError(
                f"字段 '{field_name}' 必须为有效数字，当前收到 '{raw_value}'。"
            ) from exc

    if not math.isfinite(parsed):
        raise ValueError(f"字段 '{field_name}' 必须为有限数值，当前收到 '{raw_value}'。")
    if parsed < 0:
        raise ValueError(f"字段 '{field_name}' 不能为负数（{parsed}）。")
    return round(parsed, 2)


def validate_iso_date(raw_date: Any, field_name: str = "tanggal_update") -> str:
    """严格校验 YYYY-MM-DD 格式及公历日期合法性。"""
    if raw_date is None or isinstance(raw_date, (bool, int, float, dict, list)):
        raise ValueError(f"字段 '{field_name}' 必须为 YYYY-MM-DD 格式的日期字符串。")
    cleaned = str(raw_date).strip()
    if len(cleaned) != 10 or cleaned[4] != "-" or cleaned[7] != "-":
        raise ValueError(
            f"字段 '{field_name}' 必须符合 YYYY-MM-DD 格式，当前收到 '{raw_date}'。"
        )
    try:
        parsed_date = datetime.strptime(cleaned, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(
            f"字段 '{field_name}' 不是有效的公历日期：'{raw_date}'。"
        ) from exc
    return parsed_date.strftime("%Y-%m-%d")


def validate_and_normalize_record(raw_record: dict[str, Any], row_number: int) -> InventoryRecord:
    """对单条库存记录执行完整校验与字段规范化。"""
    if not isinstance(raw_record, dict):
        raise RecordValidationError(
            f"第 {row_number} 行：记录必须为字典或 JSON 对象。",
            row_number=row_number,
        )

    missing_fields = sorted(col for col in REQUIRED_COLUMNS if col not in raw_record)
    if missing_fields:
        raise RecordValidationError(
            f"第 {row_number} 行：缺少必填字段（{', '.join(missing_fields)}）。",
            row_number=row_number,
        )

    current_field = "sku"
    try:
        sku = normalize_sku(raw_record["sku"])
        current_field = "nama_barang"
        nama_barang = normalize_text(raw_record["nama_barang"], "nama_barang")
        current_field = "kategori"
        kategori = normalize_text(raw_record["kategori"], "kategori", title_case=True)
        current_field = "lokasi_gudang"
        lokasi_gudang = normalize_text(raw_record["lokasi_gudang"], "lokasi_gudang", upper_case=True)
        current_field = "stok"
        stok = parse_non_negative_int(raw_record["stok"], "stok")
        current_field = "stok_minimum"
        stok_minimum = parse_non_negative_int(raw_record["stok_minimum"], "stok_minimum")
        current_field = "harga_satuan"
        harga_satuan = parse_non_negative_float(raw_record["harga_satuan"], "harga_satuan")
        current_field = "pemasok"
        pemasok = normalize_text(raw_record["pemasok"], "pemasok")
        current_field = "tanggal_update"
        tanggal_update = validate_iso_date(raw_record["tanggal_update"], "tanggal_update")
        return {
            "sku": sku,
            "nama_barang": nama_barang,
            "kategori": kategori,
            "lokasi_gudang": lokasi_gudang,
            "stok": stok,
            "stok_minimum": stok_minimum,
            "harga_satuan": harga_satuan,
            "pemasok": pemasok,
            "tanggal_update": tanggal_update,
        }
    except ValueError as exc:
        raise RecordValidationError(
            f"第 {row_number} 行：{exc}",
            row_number=row_number,
            field_name=current_field,
        ) from exc
