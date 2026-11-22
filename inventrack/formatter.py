"""Modul pemformatan output teks dan tabel CLI yang mendukung lebar karakter Unicode."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Any, Final

MAX_NAME_WIDTH: Final[int] = 34
MAX_CATEGORY_WIDTH: Final[int] = 18
REPORT_DIVIDER: Final[str] = "=" * 70


def format_currency_idr(amount: float) -> str:
    """Format nominal angka menjadi string mata uang Rupiah Indonesia.

    Args:
        amount: Nominal uang bertipe float atau int.

    Returns:
        String berformat seperti 'Rp1.250.000' atau 'Rp1.250.000,50'.
    """
    rounded = round(float(amount), 2)
    is_negative = rounded < 0
    abs_val = abs(rounded)
    whole_part = int(abs_val)
    frac_part = round((abs_val - whole_part) * 100)
    if frac_part == 100:
        whole_part += 1
        frac_part = 0

    whole_str = f"{whole_part:,}".replace(",", ".")
    prefix = "-Rp" if is_negative else "Rp"
    if frac_part > 0:
        return f"{prefix}{whole_str},{frac_part:02d}"
    return f"{prefix}{whole_str}"


def _display_width(text: str) -> int:
    """Hitung lebar visual karakter pada terminal monospace (mendukung karakter lebar CJK)."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1 for ch in text)


def _pad_left(text: str, width: int) -> str:
    return text + (" " * max(0, width - _display_width(text)))


def _pad_right(text: str, width: int) -> str:
    return (" " * max(0, width - _display_width(text))) + text


def _truncate_text(text: str, max_width: int) -> str:
    """Potong teks yang melebihi batas lebar visual kolom dengan elipsis."""
    if _display_width(text) <= max_width:
        return text
    if max_width <= 3:
        out: list[str] = []
        used = 0
        for ch in text:
            ch_w = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
            if used + ch_w > max_width:
                break
            out.append(ch)
            used += ch_w
        return "".join(out)

    limit = max_width - 3
    out = []
    used = 0
    for ch in text:
        ch_w = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if used + ch_w > limit:
            break
        out.append(ch)
        used += ch_w
    return "".join(out) + "..."


def format_records_table(records: Sequence[dict[str, Any]], max_rows: int | None = None) -> str:
    """Render daftar record inventaris menjadi tabel ASCII yang sejajar.

    Args:
        records: Koleksi record inventaris yang akan ditampilkan.
        max_rows: Batas maksimum jumlah baris tampil (opsional).

    Returns:
        String tabel terformat atau pesan informatif jika kosong.
    """
    if not records:
        return "(Tidak ada data barang yang cocok untuk ditampilkan.)"

    display_records = records[:max_rows] if max_rows is not None and max_rows >= 0 else records

    headers = ["SKU", "Nama Barang", "Kategori", "Gudang", "Stok", "Min", "Status", "Nilai Stok", "Restock"]
    rows: list[list[str]] = []
    for item in display_records:
        rows.append(
            [
                str(item.get("sku", "-")),
                _truncate_text(str(item.get("nama_barang", "-")), MAX_NAME_WIDTH),
                _truncate_text(str(item.get("kategori", "-")), MAX_CATEGORY_WIDTH),
                str(item.get("lokasi_gudang", "-")),
                str(item.get("stok", 0)),
                str(item.get("stok_minimum", 0)),
                str(item.get("status_stok", "-")),
                format_currency_idr(float(item.get("nilai_stok", 0.0))),
                str(item.get("rekomendasi_restock", 0)),
            ]
        )

    widths = [
        max(_display_width(headers[col_idx]), *(_display_width(row[col_idx]) for row in rows))
        for col_idx in range(len(headers))
    ]
    right_aligned = {4, 5, 7, 8}

    def _format_row(values: list[str]) -> str:
        return " | ".join(
            _pad_right(value, widths[idx]) if idx in right_aligned else _pad_left(value, widths[idx])
            for idx, value in enumerate(values)
        )

    separator = "-+-".join("-" * width for width in widths)
    lines = [_format_row(headers), separator]
    lines.extend(_format_row(row) for row in rows)
    if max_rows is not None and len(records) > len(display_records):
        lines.append(f"... ({len(records) - len(display_records)} baris lainnya tidak ditampilkan)")
    return "\n".join(lines)


def format_group_recap_table(recap: dict[str, dict[str, Any]], group_label: str = "Kelompok") -> str:
    """Render tabel rekapitulasi metrik per kelompok.

    Args:
        recap: Dictionary hasil calculate_group_recap.
        group_label: Judul kolom pertama (misal 'Kategori' atau 'Gudang').

    Returns:
        String tabel rekapitulasi yang rapi.
    """
    if not recap:
        return f"(Tidak ada data rekapitulasi {group_label.lower()}.)"

    headers = [group_label, "SKU", "Total Unit", "Total Valuasi", "Rata-rata Harga", "Kritis/Habis"]
    rows: list[list[str]] = []
    for key, stats in recap.items():
        rows.append(
            [
                key,
                str(stats["jumlah_sku"]),
                str(stats["total_unit"]),
                format_currency_idr(stats["total_valuasi"]),
                format_currency_idr(stats["rata_rata_harga"]),
                str(stats["jumlah_kritis_atau_habis"]),
            ]
        )

    widths = [
        max(_display_width(headers[col_idx]), *(_display_width(row[col_idx]) for row in rows))
        for col_idx in range(len(headers))
    ]
    right_aligned = {1, 2, 3, 4, 5}

    def _format_row(values: list[str]) -> str:
        return " | ".join(
            _pad_right(value, widths[idx]) if idx in right_aligned else _pad_left(value, widths[idx])
            for idx, value in enumerate(values)
        )

    separator = "-+-".join("-" * width for width in widths)
    lines = [_format_row(headers), separator]
    lines.extend(_format_row(row) for row in rows)
    return "\n".join(lines)


def format_rejected_rows(rejected_rows: Sequence[dict[str, Any]]) -> str:
    """Format daftar baris input yang ditolak selama validasi defensif."""
    if not rejected_rows:
        return "Tidak ada baris yang ditolak."
    lines = [f"Baris ditolak ({len(rejected_rows)}):"]
    for entry in rejected_rows:
        lines.append(
            f"  - [Baris {entry.get('row_number', '?')} | SKU: {entry.get('sku', '-')}] "
            f"{entry.get('reason', 'Alasan tidak diketahui')}"
        )
    return "\n".join(lines)


def format_duplicates_log(duplicates: Sequence[dict[str, Any]]) -> str:
    """Format log catatan duplikat SKU yang dibuang saat deduplikasi."""
    if not duplicates:
        return "Tidak ada duplikasi SKU ditemukan."
    lines = [f"Duplikat SKU ditangani ({len(duplicates)}):"]
    for entry in duplicates:
        lines.append(f"  - [{entry.get('sku', '-')}] {entry.get('reason', '')}")
    return "\n".join(lines)


def format_summary_text(summary: dict[str, Any]) -> str:
    """Render ringkasan laporan analisis inventaris lengkap untuk tampilan terminal.

    Args:
        summary: Dictionary hasil calculate_summary.

    Returns:
        String laporan terstruktur multi-bagian.
    """
    umum = summary["ringkasan_umum"]
    dist = summary["distribusi_status"]
    meta = summary["metadata_unik"]
    restock = summary["daftar_perlu_restock"]

    lines: list[str] = [
        REPORT_DIVIDER,
        "                  RINGKASAN ANALISIS INVENTARIS GUDANG                ",
        REPORT_DIVIDER,
        f"Total SKU Unik          : {umum['total_sku_unik']}",
        f"Total Unit Stok         : {umum['total_unit_stok']}",
        f"Total Valuasi Stok      : {format_currency_idr(umum['total_valuasi_idr'])}",
        f"Rata-rata Harga Satuan  : {format_currency_idr(umum['rata_rata_harga_satuan_idr'])}",
        f"Duplikat SKU Dihapus    : {umum['jumlah_duplikat_dihapus']}",
        f"Baris Input Ditolak     : {umum['jumlah_baris_ditolak']}",
    ]

    if umum["item_nilai_tertinggi"] is not None:
        top = umum["item_nilai_tertinggi"]
        low = umum["item_nilai_terendah"]
        lines.append(
            f"Valuasi Tertinggi       : {top['sku']} - {top['nama_barang']} "
            f"({format_currency_idr(top['nilai_stok'])})"
        )
        lines.append(
            f"Valuasi Terendah        : {low['sku']} - {low['nama_barang']} "
            f"({format_currency_idr(low['nilai_stok'])})"
        )

    lines.extend(
        [
            "",
            "[Distribusi Status Stok]",
            f"  HABIS    : {dist['HABIS']}",
            f"  KRITIS   : {dist['KRITIS']}",
            f"  AMAN     : {dist['AMAN']}",
            f"  BERLEBIH : {dist['BERLEBIH']}",
            "",
            "[Metadata Unik]",
            f"  Kategori ({len(meta['kategori'])}) : {', '.join(meta['kategori']) or '-'}",
            f"  Gudang   ({len(meta['lokasi_gudang'])}) : {', '.join(meta['lokasi_gudang']) or '-'}",
            f"  Pemasok  ({len(meta['pemasok'])}) : {', '.join(meta['pemasok']) or '-'}",
            "",
            "[Rekapitulasi per Kategori]",
            format_group_recap_table(summary["rekap_per_kategori"], "Kategori"),
            "",
            "[Rekapitulasi per Gudang]",
            format_group_recap_table(summary["rekap_per_gudang"], "Gudang"),
            "",
            f"[Daftar Barang Perlu Restock ({len(restock)} SKU)]",
        ]
    )

    if not restock:
        lines.append("  Semua barang berada pada level stok aman/berlebih.")
    else:
        for item in restock:
            lines.append(
                f"  - [{item['status_stok']:6}] {item['sku']} | {item['nama_barang']} "
                f"({item['lokasi_gudang']}) -> Stok: {item['stok']}/{item['stok_minimum']}, "
                f"Saran Restock: +{item['rekomendasi_restock']} unit"
            )

    if summary["log_duplikat"]:
        lines.extend(["", format_duplicates_log(summary["log_duplikat"])])
    if summary["log_baris_ditolak"]:
        lines.extend(["", format_rejected_rows(summary["log_baris_ditolak"])])

    lines.append(REPORT_DIVIDER)
    return "\n".join(lines)
