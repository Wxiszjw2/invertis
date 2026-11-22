"""Modul pembacaan dan penulisan atomik file CSV/JSON dengan penanganan error defensif."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, Literal, TypedDict

from inventrack.exceptions import (
    DataFileNotFoundError,
    InvalidDataFormatError,
    InvenTrackError,
    RecordValidationError,
    UnsupportedFormatError,
)
from inventrack.validators import (
    REQUIRED_COLUMNS,
    InventoryRecord,
    RejectedRow,
    validate_and_normalize_record,
)

FileFormat = Literal["csv", "json"]


class LoadedInventory(TypedDict):
    """Hasil pemuatan dan validasi berkas inventaris."""

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
    """Pastikan path input ada di sistem file dan berupa file reguler.

    Args:
        file_path: Lokasi file input sebagai string atau Path.

    Returns:
        Objek Path yang sudah terverifikasi keberadaannya.

    Raises:
        DataFileNotFoundError: Jika path kosong, tidak ditemukan, atau merupakan direktori.
    """
    text_path = str(file_path).strip()
    if not text_path:
        raise DataFileNotFoundError("Path file input tidak boleh kosong.")
    path = Path(text_path)
    if not path.exists():
        raise DataFileNotFoundError(f"File input tidak ditemukan: '{path}'.")
    if not path.is_file():
        raise DataFileNotFoundError(f"Path input bukan file reguler (kemungkinan direktori): '{path}'.")
    return path


def detect_file_format(file_path: Path) -> FileFormat:
    """Deteksi format file berdasarkan ekstensi (.csv atau .json).

    Args:
        file_path: Objek Path file input.

    Returns:
        Literal 'csv' atau 'json'.

    Raises:
        UnsupportedFormatError: Jika ekstensi file tidak didukung.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".json":
        return "json"
    raise UnsupportedFormatError(
        f"Format file '{suffix or '(tanpa ekstensi)'}' tidak didukung. Gunakan file .csv atau .json."
    )


def load_raw_csv(file_path: Path) -> list[tuple[int, dict[str, Any]]]:
    """Baca baris mentah dari file CSV ber-encoding UTF-8 atau UTF-8 BOM.

    Args:
        file_path: Path ke file CSV input.

    Returns:
        List tuple (nomor_baris_csv, dict_baris_mentah) dengan nomor baris mulai dari 2.

    Raises:
        InvalidDataFormatError: Jika header kosong, kolom wajib hilang, atau file CSV rusak.
    """
    try:
        with file_path.open(mode="r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise InvalidDataFormatError(
                    f"File CSV '{file_path}' kosong atau tidak memiliki baris header."
                )

            cleaned_fieldnames = [
                name.strip() if isinstance(name, str) else "" for name in reader.fieldnames
            ]
            reader.fieldnames = cleaned_fieldnames

            missing_columns = sorted(REQUIRED_COLUMNS - set(cleaned_fieldnames))
            if missing_columns:
                raise InvalidDataFormatError(
                    f"Header CSV pada '{file_path}' tidak lengkap. Kolom wajib yang hilang: "
                    f"{', '.join(missing_columns)}."
                )

            return [(row_num, dict(row)) for row_num, row in enumerate(reader, start=2)]
    except (UnicodeDecodeError, csv.Error, OSError) as exc:
        raise InvalidDataFormatError(f"Gagal membaca file CSV '{file_path}': {exc}") from exc


def load_raw_json(file_path: Path) -> list[tuple[int, Any]]:
    """Baca elemen mentah dari file JSON (berupa array objek atau objek dengan key 'items').

    Args:
        file_path: Path ke file JSON input.

    Returns:
        List tuple (indeks_item_1_based, item_mentah).

    Raises:
        InvalidDataFormatError: Jika sintaks JSON rusak atau struktur root bukan list/items.
    """
    try:
        with file_path.open(mode="r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise InvalidDataFormatError(f"Gagal mem-parsing file JSON '{file_path}': {exc}") from exc

    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
    else:
        raise InvalidDataFormatError(
            f"Struktur root JSON pada '{file_path}' harus berupa array objek [...] "
            "atau object dengan key 'items' bertipe list."
        )

    return [(index, item) for index, item in enumerate(items, start=1)]


def load_inventory(file_path: str | Path, *, strict: bool = False) -> LoadedInventory:
    """Muat dan validasi seluruh data inventaris dari file CSV atau JSON.

    Pada mode non-strict (default), baris yang tidak valid diisolasi ke daftar
    'rejected_rows' agar baris valid lainnya tetap dapat diproses.

    Args:
        file_path: Lokasi file CSV atau JSON.
        strict: Jika True, langsung hentikan proses bila ada minimal satu baris tidak valid.

    Returns:
        LoadedInventory berisi source_file, format, total_raw_rows, records, dan rejected_rows.

    Raises:
        DataFileNotFoundError: Jika file tidak ditemukan.
        UnsupportedFormatError: Jika format file bukan .csv/.json.
        InvalidDataFormatError: Jika header/struktur rusak atau ada baris gagal saat strict=True.
    """
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
                        f"Baris {row_number}: item JSON harus berupa object, "
                        f"diterima {type(raw_row).__name__}."
                    ),
                }
            )
            continue

        if None in raw_row:
            rejected_rows.append(
                {
                    "row_number": row_number,
                    "sku": str(raw_row.get("sku") or "-").strip() or "-",
                    "reason": f"Baris {row_number}: jumlah kolom melebihi definisi header CSV.",
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
            f"Mode strict gagal: ditemukan {len(rejected_rows)} baris tidak valid. "
            f"Contoh pertama -> {first_reason}"
        )

    return {
        "source_file": str(path),
        "format": file_format,
        "total_raw_rows": len(raw_rows),
        "records": valid_records,
        "rejected_rows": rejected_rows,
    }


def save_inventory_csv(records: Sequence[dict[str, Any]], output_path: str | Path) -> Path:
    """Simpan daftar record inventaris secara atomik ke file CSV UTF-8 dengan header baku.

    Menulis ke berkas sementara terlebih dahulu lalu melakukan os.replace agar berkas
    tujuan tidak pernah terpotong atau korup jika terjadi kegagalan di tengah penulisan.

    Args:
        records: Koleksi dictionary record inventaris (aman meskipun kosong).
        output_path: Tujuan path file CSV keluaran.

    Returns:
        Objek Path file CSV yang berhasil ditulis.

    Raises:
        InvenTrackError: Jika terjadi kegagalan I/O saat menulis file.
    """
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
        raise InvenTrackError(f"Gagal menyimpan file CSV ke '{destination}': {exc}") from exc
    return destination


def save_report_json(report: dict[str, Any], output_path: str | Path) -> Path:
    """Simpan laporan analisis secara atomik ke file JSON UTF-8.

    Args:
        report: Dictionary laporan analisis yang JSON-serializable.
        output_path: Tujuan path file JSON keluaran.

    Returns:
        Objek Path file JSON yang berhasil ditulis.

    Raises:
        InvenTrackError: Jika data tidak dapat diserialisasi atau penulisan file gagal.
    """
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
        raise InvenTrackError(f"Gagal menyimpan laporan JSON ke '{destination}': {exc}") from exc
    return destination
