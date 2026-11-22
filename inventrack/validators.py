"""Skema tipe domain, konstanta aturan, dan fungsi validasi field inventaris."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Final, Literal, TypedDict

from inventrack.exceptions import RecordValidationError

StockStatus = Literal["HABIS", "KRITIS", "AMAN", "BERLEBIH"]
DedupStrategy = Literal["latest", "first"]
GroupField = Literal["kategori", "lokasi_gudang", "status_stok", "pemasok"]


class InventoryRecord(TypedDict):
    """Struktur dictionary satu record inventaris yang telah tervalidasi."""

    sku: str
    nama_barang: str
    kategori: str
    lokasi_gudang: str
    stok: int
    stok_minimum: int
    harga_satuan: float
    pemasok: str
    tanggal_update: str


class EnrichedRecord(InventoryRecord):
    """Record inventaris yang telah diperkaya kolom kalkulasi turunan."""

    nilai_stok: float
    status_stok: StockStatus
    rekomendasi_restock: int


class RejectedRow(TypedDict):
    """Catatan baris input yang ditolak selama validasi defensif."""

    row_number: int
    sku: str
    reason: str


class DuplicateEntry(TypedDict):
    """Catatan audit penanganan duplikasi kode SKU."""

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
VALID_STATUSES: Final[frozenset[str]] = frozenset({"HABIS", "KRITIS", "AMAN", "BERLEBIH"})
VALID_DEDUP_STRATEGIES: Final[frozenset[str]] = frozenset({"latest", "first"})
VALID_GROUP_FIELDS: Final[frozenset[str]] = frozenset(
    {"kategori", "lokasi_gudang", "status_stok", "pemasok"}
)


def normalize_sku(raw_sku: Any) -> str:
    """Normalisasi kode SKU dengan memangkas spasi berlebih dan mengubah ke huruf kapital.

    Args:
        raw_sku: Nilai mentah kode SKU dari CSV atau JSON.

    Returns:
        Kode SKU bersih dalam huruf kapital.

    Raises:
        ValueError: Jika nilai SKU kosong, None, atau bertipe koleksi/boolean.
    """
    if raw_sku is None or isinstance(raw_sku, (bool, dict, list)):
        raise ValueError("Kolom 'sku' wajib diisi dengan teks yang valid.")
    cleaned = " ".join(str(raw_sku).split()).upper()
    if not cleaned:
        raise ValueError("Kolom 'sku' tidak boleh kosong.")
    return cleaned


def normalize_text(
    raw_value: Any,
    field_name: str,
    *,
    title_case: bool = False,
    upper_case: bool = False,
) -> str:
    """Bersihkan spasi berlebih pada nilai teks dan pastikan tidak kosong.

    Args:
        raw_value: Nilai teks mentah.
        field_name: Nama kolom untuk pesan error yang jelas.
        title_case: Jika True, ubah hasil ke Title Case.
        upper_case: Jika True, ubah hasil ke HURUF KAPITAL.

    Returns:
        String bersih dengan spasi internal tunggal.

    Raises:
        ValueError: Jika nilai kosong, None, atau bertipe koleksi/boolean.
    """
    if raw_value is None or isinstance(raw_value, (bool, dict, list)):
        raise ValueError(f"Kolom '{field_name}' wajib diisi dengan teks yang valid.")
    cleaned = " ".join(str(raw_value).split())
    if not cleaned:
        raise ValueError(f"Kolom '{field_name}' tidak boleh kosong.")
    if upper_case:
        return cleaned.upper()
    if title_case:
        return cleaned.title()
    return cleaned


def parse_non_negative_int(raw_value: Any, field_name: str) -> int:
    """Parse dan validasi bilangan bulat non-negatif (>= 0).

    Menolak boolean, None, string kosong, angka pecahan (misal '4.5'), dan negatif.

    Args:
        raw_value: Nilai mentah bilangan bulat.
        field_name: Nama kolom untuk pelaporan kesalahan.

    Returns:
        Integer non-negatif hasil parsing.

    Raises:
        ValueError: Jika nilai bukan bilangan bulat valid atau bernilai negatif.
    """
    if raw_value is None or isinstance(raw_value, (bool, dict, list)):
        raise ValueError(f"Kolom '{field_name}' harus berupa bilangan bulat non-negatif.")
    if isinstance(raw_value, int):
        parsed = raw_value
    elif isinstance(raw_value, float):
        if not math.isfinite(raw_value) or not raw_value.is_integer():
            raise ValueError(
                f"Kolom '{field_name}' tidak menerima angka desimal atau non-hingga ({raw_value})."
            )
        parsed = int(raw_value)
    else:
        text = str(raw_value).strip()
        if not text:
            raise ValueError(f"Kolom '{field_name}' tidak boleh kosong.")
        try:
            parsed = int(text)
        except ValueError as exc:
            raise ValueError(
                f"Kolom '{field_name}' harus berupa bilangan bulat tanpa desimal, diterima '{raw_value}'."
            ) from exc

    if parsed < 0:
        raise ValueError(f"Kolom '{field_name}' tidak boleh bernilai negatif ({parsed}).")
    return parsed


def parse_non_negative_float(raw_value: Any, field_name: str) -> float:
    """Parse dan validasi bilangan desimal non-negatif (>= 0) yang finite.

    Args:
        raw_value: Nilai numerik mentah.
        field_name: Nama kolom untuk pesan error.

    Returns:
        Float non-negatif dibulatkan ke 2 angka di belakang koma.

    Raises:
        ValueError: Jika nilai bukan angka finite atau bernilai negatif.
    """
    if raw_value is None or isinstance(raw_value, (bool, dict, list)):
        raise ValueError(f"Kolom '{field_name}' harus berupa angka non-negatif.")
    if isinstance(raw_value, (int, float)):
        parsed = float(raw_value)
    else:
        text = str(raw_value).strip()
        if not text:
            raise ValueError(f"Kolom '{field_name}' tidak boleh kosong.")
        try:
            parsed = float(text)
        except ValueError as exc:
            raise ValueError(
                f"Kolom '{field_name}' harus berupa angka yang valid, diterima '{raw_value}'."
            ) from exc

    if not math.isfinite(parsed):
        raise ValueError(f"Kolom '{field_name}' harus berupa angka finite, diterima '{raw_value}'.")
    if parsed < 0:
        raise ValueError(f"Kolom '{field_name}' tidak boleh bernilai negatif ({parsed}).")
    return round(parsed, 2)


def validate_iso_date(raw_date: Any, field_name: str = "tanggal_update") -> str:
    """Validasi tanggal dalam format ketat YYYY-MM-DD sesuai kalender.

    Args:
        raw_date: Nilai tanggal mentah.
        field_name: Nama kolom untuk pesan error.

    Returns:
        String tanggal tervalidasi berformat YYYY-MM-DD.

    Raises:
        ValueError: Jika format tanggal bukan YYYY-MM-DD atau tanggal kalender tidak sah.
    """
    if raw_date is None or isinstance(raw_date, (bool, int, float, dict, list)):
        raise ValueError(f"Kolom '{field_name}' harus berupa string tanggal YYYY-MM-DD.")
    cleaned = str(raw_date).strip()
    if len(cleaned) != 10 or cleaned[4] != "-" or cleaned[7] != "-":
        raise ValueError(
            f"Kolom '{field_name}' harus berformat YYYY-MM-DD, diterima '{raw_date}'."
        )
    try:
        parsed_date = datetime.strptime(cleaned, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(
            f"Kolom '{field_name}' bukan tanggal kalender yang valid: '{raw_date}'."
        ) from exc
    return parsed_date.strftime("%Y-%m-%d")


def validate_and_normalize_record(raw_record: dict[str, Any], row_number: int) -> InventoryRecord:
    """Validasi dan normalisasi satu record inventaris secara menyeluruh.

    Args:
        raw_record: Dictionary mentah hasil pembacaan satu baris CSV atau satu elemen JSON.
        row_number: Nomor baris atau indeks item (1-based JSON / 2-based CSV) untuk konteks error.

    Returns:
        InventoryRecord bersih, bertipe tepat, dan siap diproses.

    Raises:
        RecordValidationError: Jika ada field wajib yang hilang atau gagal validasi.
    """
    if not isinstance(raw_record, dict):
        raise RecordValidationError(
            f"Baris {row_number}: record harus berupa dictionary/object.",
            row_number=row_number,
        )

    missing_fields = sorted(col for col in REQUIRED_COLUMNS if col not in raw_record)
    if missing_fields:
        raise RecordValidationError(
            f"Baris {row_number}: field wajib tidak ditemukan ({', '.join(missing_fields)}).",
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
            f"Baris {row_number}: {exc}",
            row_number=row_number,
            field_name=current_field,
        ) from exc
