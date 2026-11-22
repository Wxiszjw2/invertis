"""Logika inti pemrosesan, transformasi imutabel, dan analitik inventaris."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from inventrack.exceptions import InvalidUserInputError
from inventrack.validators import (
    VALID_DEDUP_STRATEGIES,
    VALID_GROUP_FIELDS,
    VALID_STATUSES,
    DuplicateEntry,
    EnrichedRecord,
    StockStatus,
)

RESTOCK_BUFFER_MULTIPLIER: Final[int] = 2
OVERSTOCK_MULTIPLIER: Final[int] = 5
STATUS_ORDER: Final[tuple[StockStatus, ...]] = ("HABIS", "KRITIS", "AMAN", "BERLEBIH")
SEARCHABLE_FIELDS: Final[tuple[str, ...]] = (
    "sku",
    "nama_barang",
    "kategori",
    "pemasok",
    "lokasi_gudang",
)


def classify_stock_status(stok: int, stok_minimum: int) -> StockStatus:
    """Klasifikasikan status ketersediaan stok barang berdasarkan ambang batas minimum.

    Args:
        stok: Jumlah unit stok saat ini.
        stok_minimum: Ambang batas minimum stok pengaman.

    Returns:
        Salah satu label status: 'HABIS', 'KRITIS', 'AMAN', atau 'BERLEBIH'.
    """
    if stok == 0:
        return "HABIS"
    if stok <= stok_minimum:
        return "KRITIS"
    if stok_minimum > 0 and stok > stok_minimum * OVERSTOCK_MULTIPLIER:
        return "BERLEBIH"
    return "AMAN"


def calculate_restock_recommendation(stok: int, stok_minimum: int, status_stok: str) -> int:
    """Hitung rekomendasi jumlah unit pengisian ulang (restock) untuk stok kritis/habis.

    Target pengisian ulang ditetapkan sebesar RESTOCK_BUFFER_MULTIPLIER * stok_minimum.

    Args:
        stok: Jumlah unit tersedia saat ini.
        stok_minimum: Ambang batas minimum stok.
        status_stok: Label status hasil klasifikasi stok.

    Returns:
        Jumlah unit yang disarankan untuk dibeli ulang (>= 0).
    """
    if status_stok in {"HABIS", "KRITIS"}:
        target_buffer = stok_minimum * RESTOCK_BUFFER_MULTIPLIER
        return max(0, target_buffer - stok)
    return 0


def _enrich_single_record(record: dict[str, Any]) -> EnrichedRecord:
    """Buat salinan record baru lengkap dengan kolom turunan hasil kalkulasi."""
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


def enrich_records(records: Sequence[dict[str, Any]]) -> list[EnrichedRecord]:
    """Tambahkan nilai_stok, status_stok, dan rekomendasi_restock tanpa memutasi input.

    Args:
        records: Koleksi record inventaris yang sudah lolos validasi.

    Returns:
        List baru berisi dictionary record yang telah diperkaya kolom turunannya.
    """
    return [_enrich_single_record(record) for record in records]


def deduplicate_records(
    records: Sequence[dict[str, Any]],
    strategy: str = "latest",
) -> tuple[list[dict[str, Any]], list[DuplicateEntry]]:
    """Hapus duplikat SKU menggunakan set untuk deteksi O(1) dan dict untuk retensi.

    Args:
        records: Koleksi record inventaris yang mungkin memiliki duplikasi SKU.
        strategy: Strategi pemilihan record duplikat ('latest' berdasarkan tanggal_update
            terbaru, atau 'first' mempertahankan kemunculan pertama).

    Returns:
        Tuple berisi (list record unik terurut, list catatan duplikat yang dibuang).

    Raises:
        InvalidUserInputError: Jika strategi deduplikasi tidak dikenali.
    """
    normalized_strategy = strategy.strip().lower()
    if normalized_strategy not in VALID_DEDUP_STRATEGIES:
        raise InvalidUserInputError(
            f"Strategi deduplikasi '{strategy}' tidak valid. Pilih 'latest' atau 'first'."
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
                        f"Digantikan oleh record lebih baru ({record['tanggal_update']} > "
                        f"{existing['tanggal_update']})."
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
                        f"Dipertahankan record awal ({existing['tanggal_update']}) "
                        f"berdasarkan strategi '{normalized_strategy}'."
                    ),
                }
            )

    return list(selected_by_sku.values()), duplicates


def build_sku_index(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Bangun indeks dictionary pemetaan SKU ke record untuk lookup O(1).

    Args:
        records: Koleksi record inventaris unik.

    Returns:
        Dictionary dengan key berupa kode SKU dan value berupa record barang.
    """
    return {str(item["sku"]): item for item in records}


def search_records(records: Sequence[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Cari barang dengan prioritas exact-match SKU O(1), lalu substring case-insensitive.

    Args:
        records: Koleksi record inventaris.
        query: Kata kunci pencarian (SKU, nama barang, kategori, pemasok, atau gudang).

    Returns:
        List record yang cocok dengan kata kunci pencarian.

    Raises:
        InvalidUserInputError: Jika query kosong atau hanya berisi spasi.
    """
    if not isinstance(query, str) or not query.strip():
        raise InvalidUserInputError("Kata kunci pencarian (--query) tidak boleh kosong.")

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
    """Saring record inventaris berdasarkan kombinasi kriteria multi-atribut.

    Args:
        records: Koleksi record inventaris (sebaiknya sudah diperkaya dengan status_stok).
        kategori: Filter kategori barang (case-insensitive exact match).
        lokasi: Filter kode gudang (case-insensitive exact match).
        status: Filter status stok ('HABIS', 'KRITIS', 'AMAN', 'BERLEBIH').
        min_harga: Batas bawah harga satuan (>= 0).
        max_harga: Batas atas harga satuan (>= min_harga).

    Returns:
        List baru berisi record yang memenuhi seluruh kriteria filter aktif.

    Raises:
        InvalidUserInputError: Jika nilai status tidak dikenal atau rentang harga tidak valid.
    """
    normalized_status: str | None = None
    if status is not None and status.strip():
        normalized_status = status.strip().upper()
        if normalized_status not in VALID_STATUSES:
            raise InvalidUserInputError(
                f"Status '{status}' tidak valid. Pilihan: {', '.join(sorted(VALID_STATUSES))}."
            )

    if min_harga is not None and min_harga < 0:
        raise InvalidUserInputError("Filter min_harga tidak boleh bernilai negatif.")
    if max_harga is not None and max_harga < 0:
        raise InvalidUserInputError("Filter max_harga tidak boleh bernilai negatif.")
    if min_harga is not None and max_harga is not None and min_harga > max_harga:
        raise InvalidUserInputError(
            f"Rentang harga tidak valid: min_harga ({min_harga}) lebih besar dari max_harga ({max_harga})."
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
    """Kelompokkan record inventaris ke dalam dictionary berdasarkan field tertentu.

    Args:
        records: Koleksi record inventaris.
        group_by: Nama atribut pengelompokan ('kategori', 'lokasi_gudang', 'status_stok', 'pemasok').

    Returns:
        Dictionary terurut alfabetis dengan key nama kelompok dan value list record.

    Raises:
        InvalidUserInputError: Jika atribut pengelompokan tidak diizinkan.
    """
    field = group_by.strip().lower()
    if field not in VALID_GROUP_FIELDS:
        raise InvalidUserInputError(
            f"Field pengelompokan '{group_by}' tidak valid. Pilihan: {', '.join(sorted(VALID_GROUP_FIELDS))}."
        )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = str(record.get(field, "TIDAK_DIKETAHUI"))
        grouped.setdefault(key, []).append(record)

    return {key: grouped[key] for key in sorted(grouped)}


def extract_unique_metadata(records: Sequence[dict[str, Any]]) -> dict[str, set[str]]:
    """Ekstrak himpunan nilai unik kategori, gudang, pemasok, dan status dengan set comprehension.

    Args:
        records: Koleksi record inventaris.

    Returns:
        Dictionary berisi set unik untuk setiap dimensi metadata.
    """
    return {
        "kategori": {str(item["kategori"]) for item in records},
        "lokasi_gudang": {str(item["lokasi_gudang"]) for item in records},
        "pemasok": {str(item["pemasok"]) for item in records},
        "status_stok": {str(item["status_stok"]) for item in records if "status_stok" in item},
    }


def _summarize_group(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Hitung metrik agregat satu kelompok secara aman terhadap kelompok kosong."""
    count = len(items)
    if count == 0:
        return {
            "jumlah_sku": 0,
            "total_unit": 0,
            "total_valuasi": 0.0,
            "rata_rata_harga": 0.0,
            "jumlah_kritis_atau_habis": 0,
        }

    total_unit = sum(int(item["stok"]) for item in items)
    total_valuasi = round(sum(float(item.get("nilai_stok", 0.0)) for item in items), 2)
    rata_rata_harga = round(sum(float(item["harga_satuan"]) for item in items) / count, 2)
    jumlah_kritis_atau_habis = sum(
        1 for item in items if item.get("status_stok") in {"HABIS", "KRITIS"}
    )
    return {
        "jumlah_sku": count,
        "total_unit": total_unit,
        "total_valuasi": total_valuasi,
        "rata_rata_harga": rata_rata_harga,
        "jumlah_kritis_atau_habis": jumlah_kritis_atau_habis,
    }


def calculate_group_recap(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Hitung rekapitulasi metrik untuk setiap kelompok hasil group_records.

    Args:
        grouped: Dictionary hasil pengelompokan record.

    Returns:
        Dictionary berisi statistik ringkas per nama kelompok.
    """
    return {key: _summarize_group(items) for key, items in grouped.items()}


def calculate_summary(
    records: Sequence[dict[str, Any]],
    *,
    duplicates_removed: Sequence[dict[str, Any]] | None = None,
    rejected_rows: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Hitung laporan rekapitulasi lengkap inventaris secara defensif untuk data normal maupun kosong.

    Args:
        records: Koleksi record unik yang sudah diperkaya (enriched).
        duplicates_removed: Catatan duplikat SKU yang dihapus saat deduplikasi.
        rejected_rows: Catatan baris input yang gagal validasi.

    Returns:
        Dictionary ringkasan komprehensif yang siap ditampilkan atau diekspor ke JSON.
    """
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
            if item.get("status_stok") in {"HABIS", "KRITIS"}
        ],
        key=lambda row: (0 if row["status_stok"] == "HABIS" else 1, row["stok"], row["sku"]),
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
        "ringkasan_umum": {
            "total_sku_unik": total_sku,
            "total_unit_stok": total_unit,
            "total_valuasi_idr": total_valuasi,
            "rata_rata_harga_satuan_idr": rata_rata_harga,
            "jumlah_duplikat_dihapus": len(dup_list),
            "jumlah_baris_ditolak": len(rej_list),
            "item_nilai_tertinggi": item_tertinggi,
            "item_nilai_terendah": item_terendah,
        },
        "distribusi_status": distribusi_status,
        "metadata_unik": {key: sorted(values) for key, values in unique_meta.items()},
        "rekap_per_kategori": rekap_kategori,
        "rekap_per_gudang": rekap_gudang,
        "daftar_perlu_restock": daftar_perlu_restock,
        "log_duplikat": dup_list,
        "log_baris_ditolak": rej_list,
    }
