"""库存数据处理、去重、检索、筛选、分组与统计分析核心模块。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from inventrack_zh.exceptions import InvalidUserInputError
from inventrack_zh.validators import (
    VALID_DEDUP_STRATEGIES,
    VALID_GROUP_FIELDS,
    VALID_STATUSES,
    DuplicateEntry,
    EnrichedRecordZh,
    StockStatusZh,
)

RESTOCK_BUFFER_MULTIPLIER: Final[int] = 2
OVERSTOCK_MULTIPLIER: Final[int] = 5
STATUS_ORDER: Final[tuple[StockStatusZh, ...]] = ("缺货", "预警", "正常", "积压")
SEARCHABLE_FIELDS: Final[tuple[str, ...]] = (
    "sku",
    "nama_barang",
    "kategori",
    "pemasok",
    "lokasi_gudang",
)

STATUS_ALIASES: Final[dict[str, StockStatusZh]] = {
    "HABIS": "缺货",
    "KRITIS": "预警",
    "AMAN": "正常",
    "BERLEBIH": "积压",
}


def classify_stock_status(stok: int, stok_minimum: int) -> StockStatusZh:
    """根据当前库存与最低安全库存阈值划分库存状态。"""
    if stok == 0:
        return "缺货"
    if stok <= stok_minimum:
        return "预警"
    if stok_minimum > 0 and stok > stok_minimum * OVERSTOCK_MULTIPLIER:
        return "积压"
    return "正常"


def calculate_restock_recommendation(stok: int, stok_minimum: int, status_stok: str) -> int:
    """计算缺货或预警物料的建议补货数量（目标缓冲量为 2 倍安全库存）。"""
    if status_stok in {"缺货", "预警"}:
        target_buffer = stok_minimum * RESTOCK_BUFFER_MULTIPLIER
        return max(0, target_buffer - stok)
    return 0


def _enrich_single_record(record: dict[str, Any]) -> EnrichedRecordZh:
    """为单条记录生成包含衍生指标的新字典（不修改原对象）。"""
    stok = int(record["stok"])
    stok_minimum = int(record["stok_minimum"])
    harga_satuan = float(record["harga_satuan"])
    status_stok = classify_stock_status(stok, stok_minimum)
    nilai_stok = round(stok * harga_satuan, 2)
    rekomendasi_restock = calculate_restock_recommendation(stok, stok_minimum, status_stok)

    return {
        "sku": str(record["sku"]),
        "nama_barang": str(record["nama_barang"]),
        "kategori": str(record["kategori"]),
        "lokasi_gudang": str(record["lokasi_gudang"]),
        "stok": stok,
        "stok_minimum": stok_minimum,
        "harga_satuan": harga_satuan,
        "pemasok": str(record["pemasok"]),
        "tanggal_update": str(record["tanggal_update"]),
        "nilai_stok": nilai_stok,
        "status_stok": status_stok,
        "rekomendasi_restock": rekomendasi_restock,
    }


def enrich_records(records: Sequence[dict[str, Any]]) -> list[EnrichedRecordZh]:
    """批量补充库存估值、状态标签与建议补货量，不修改输入集合。"""
    return [_enrich_single_record(record) for record in records]


def deduplicate_records(
    records: Sequence[dict[str, Any]],
    strategy: str = "latest",
) -> tuple[list[dict[str, Any]], list[DuplicateEntry]]:
    """使用集合实现 O(1) 重复检测并按指定策略保留唯一 SKU 记录。"""
    normalized_strategy = strategy.strip().lower()
    if normalized_strategy not in VALID_DEDUP_STRATEGIES:
        raise InvalidUserInputError(
            f"无效的去重策略 '{strategy}'，请选择 'latest' 或 'first'。"
        )

    seen_skus: set[str] = set()
    selected_by_sku: dict[str, dict[str, Any]] = {}
    duplicates: list[DuplicateEntry] = []

    for record in records:
        sku = str(record["sku"])
        if sku not in seen_skus:
            seen_skus.add(sku)
            selected_by_sku[sku] = record
            continue

        existing = selected_by_sku[sku]
        if normalized_strategy == "latest" and record["tanggal_update"] > existing["tanggal_update"]:
            selected_by_sku[sku] = record
            duplicates.append(
                {
                    "sku": sku,
                    "strategy": normalized_strategy,
                    "kept_tanggal": str(record["tanggal_update"]),
                    "discarded_tanggal": str(existing["tanggal_update"]),
                    "discarded_nama": str(existing["nama_barang"]),
                    "reason": (
                        f"已被更新记录替代（{record['tanggal_update']} > "
                        f"{existing['tanggal_update']}）。"
                    ),
                }
            )
        else:
            duplicates.append(
                {
                    "sku": sku,
                    "strategy": normalized_strategy,
                    "kept_tanggal": str(existing["tanggal_update"]),
                    "discarded_tanggal": str(record["tanggal_update"]),
                    "discarded_nama": str(record["nama_barang"]),
                    "reason": (
                        f"根据 '{normalized_strategy}' 策略保留初始记录（{existing['tanggal_update']}）。"
                    ),
                }
            )

    return list(selected_by_sku.values()), duplicates


def build_sku_index(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """构建 SKU 到库存记录的字典索引以支持 O(1) 精确查找。"""
    return {str(item["sku"]): item for item in records}


def search_records(records: Sequence[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """优先使用 O(1) SKU 精确匹配，否则执行跨字段不区分大小写子串搜索。"""
    if not isinstance(query, str) or not query.strip():
        raise InvalidUserInputError("搜索关键词（--query）不能为空。")

    cleaned_query = query.strip()
    sku_index = build_sku_index(records)
    exact_sku = cleaned_query.upper()
    if exact_sku in sku_index:
        return [sku_index[exact_sku]]

    keyword = cleaned_query.lower()
    return [
        item
        for item in records
        if any(keyword in str(item.get(field, "")).lower() for field in SEARCHABLE_FIELDS)
    ]


def filter_records(
    records: Sequence[dict[str, Any]],
    *,
    kategori: str | None = None,
    lokasi: str | None = None,
    status: str | None = None,
    min_harga: float | None = None,
    max_harga: float | None = None,
) -> list[dict[str, Any]]:
    """按多条件组合筛选库存记录。"""
    normalized_status: str | None = None
    if status is not None and status.strip():
        candidate = status.strip()
        upper_candidate = candidate.upper()
        normalized_status = STATUS_ALIASES.get(upper_candidate, candidate)
        if normalized_status not in VALID_STATUSES:
            raise InvalidUserInputError(
                f"状态 '{status}' 无效，可选值：{', '.join(sorted(VALID_STATUSES))}。"
            )

    if min_harga is not None and min_harga < 0:
        raise InvalidUserInputError("筛选参数 min_harga 不能为负数。")
    if max_harga is not None and max_harga < 0:
        raise InvalidUserInputError("筛选参数 max_harga 不能为负数。")
    if min_harga is not None and max_harga is not None and min_harga > max_harga:
        raise InvalidUserInputError(
            f"价格区间无效：最低价（{min_harga}）大于最高价（{max_harga}）。"
        )

    cleaned_kategori = " ".join(kategori.split()).lower() if kategori and kategori.strip() else None
    cleaned_lokasi = " ".join(lokasi.split()).upper() if lokasi and lokasi.strip() else None

    def _matches(item: dict[str, Any]) -> bool:
        if cleaned_kategori is not None and str(item["kategori"]).lower() != cleaned_kategori:
            return False
        if cleaned_lokasi is not None and str(item["lokasi_gudang"]).upper() != cleaned_lokasi:
            return False
        if normalized_status is not None and item.get("status_stok") != normalized_status:
            return False
        if min_harga is not None and float(item["harga_satuan"]) < min_harga:
            return False
        if max_harga is not None and float(item["harga_satuan"]) > max_harga:
            return False
        return True

    return [item for item in records if _matches(item)]


def group_records(
    records: Sequence[dict[str, Any]],
    group_by: str = "kategori",
) -> dict[str, list[dict[str, Any]]]:
    """按指定维度字段对库存记录进行分组排序。"""
    field = group_by.strip().lower()
    if field not in VALID_GROUP_FIELDS:
        raise InvalidUserInputError(
            f"分组字段 '{group_by}' 无效，可选值：{', '.join(sorted(VALID_GROUP_FIELDS))}。"
        )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = str(record.get(field, "未知"))
        grouped.setdefault(key, []).append(record)

    return {key: grouped[key] for key in sorted(grouped)}


def extract_unique_metadata(records: Sequence[dict[str, Any]]) -> dict[str, set[str]]:
    """利用集合推导式提取类别、仓库、供应商及状态的唯一集合。"""
    return {
        "kategori": {str(item["kategori"]) for item in records},
        "lokasi_gudang": {str(item["lokasi_gudang"]) for item in records},
        "pemasok": {str(item["pemasok"]) for item in records},
        "status_stok": {str(item["status_stok"]) for item in records if "status_stok" in item},
    }


def _summarize_group(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """安全计算单个分组的汇总指标（兼容空分组）。"""
    count = len(items)
    if count == 0:
        return {
            "sku_count": 0,
            "total_units": 0,
            "total_valuation": 0.0,
            "average_price": 0.0,
            "critical_or_out_count": 0,
        }

    total_unit = sum(int(item["stok"]) for item in items)
    total_valuasi = round(sum(float(item.get("nilai_stok", 0.0)) for item in items), 2)
    rata_rata_harga = round(sum(float(item["harga_satuan"]) for item in items) / count, 2)
    jumlah_kritis_atau_habis = sum(
        1 for item in items if item.get("status_stok") in {"缺货", "预警"}
    )
    return {
        "sku_count": count,
        "total_units": total_unit,
        "total_valuation": total_valuasi,
        "average_price": rata_rata_harga,
        "critical_or_out_count": jumlah_kritis_atau_habis,
    }


def calculate_group_recap(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """计算所有分组的聚合统计指标。"""
    return {key: _summarize_group(items) for key, items in grouped.items()}


def calculate_summary(
    records: Sequence[dict[str, Any]],
    *,
    duplicates_removed: Sequence[dict[str, Any]] | None = None,
    rejected_rows: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """生成完整防御式分析摘要（同时兼容常规与空数据集）。"""
    dup_list = list(duplicates_removed) if duplicates_removed is not None else []
    rej_list = list(rejected_rows) if rejected_rows is not None else []

    unique_meta = extract_unique_metadata(records)
    rekap_kategori = calculate_group_recap(group_records(records, "kategori"))
    rekap_gudang = calculate_group_recap(group_records(records, "lokasi_gudang"))
    distribusi_status = {
        status: sum(1 for item in records if item.get("status_stok") == status)
        for status in STATUS_ORDER
    }

    daftar_perlu_restock = sorted(
        [
            {
                "sku": item["sku"],
                "nama_barang": item["nama_barang"],
                "lokasi_gudang": item["lokasi_gudang"],
                "stok": item["stok"],
                "stok_minimum": item["stok_minimum"],
                "status_stok": item["status_stok"],
                "rekomendasi_restock": item["rekomendasi_restock"],
            }
            for item in records
            if item.get("status_stok") in {"缺货", "预警"}
        ],
        key=lambda row: (0 if row["status_stok"] == "缺货" else 1, row["stok"], row["sku"]),
    )

    total_sku = len(records)
    if total_sku == 0:
        total_unit = 0
        total_valuasi = 0.0
        rata_rata_harga = 0.0
        item_tertinggi = None
        item_terendah = None
    else:
        total_unit = sum(int(item["stok"]) for item in records)
        total_valuasi = round(sum(float(item.get("nilai_stok", 0.0)) for item in records), 2)
        rata_rata_harga = round(sum(float(item["harga_satuan"]) for item in records) / total_sku, 2)
        highest = max(records, key=lambda item: float(item.get("nilai_stok", 0.0)))
        lowest = min(records, key=lambda item: float(item.get("nilai_stok", 0.0)))
        item_tertinggi = {
            "sku": highest["sku"],
            "nama_barang": highest["nama_barang"],
            "nilai_stok": highest["nilai_stok"],
        }
        item_terendah = {
            "sku": lowest["sku"],
            "nama_barang": lowest["nama_barang"],
            "nilai_stok": lowest["nilai_stok"],
        }

    return {
        "总体摘要": {
            "唯一SKU总数": total_sku,
            "库存总件数": total_unit,
            "库存总估值IDR": total_valuasi,
            "平均单价IDR": rata_rata_harga,
            "已处理重复数": len(dup_list),
            "已拒绝行数": len(rej_list),
            "最高估值商品": item_tertinggi,
            "最低估值商品": item_terendah,
        },
        "状态分布": distribusi_status,
        "唯一元数据": {key: sorted(values) for key, values in unique_meta.items()},
        "按类别汇总": rekap_kategori,
        "按仓库汇总": rekap_gudang,
        "需补货清单": daftar_perlu_restock,
        "去重日志": dup_list,
        "拒绝行日志": rej_list,
    }
