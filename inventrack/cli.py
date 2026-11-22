"""Antarmuka command line (subcommand & mode interaktif) untuk InvenTrack CLI."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from inventrack.exceptions import InvalidUserInputError, InvenTrackError
from inventrack.formatter import (
    format_duplicates_log,
    format_group_recap_table,
    format_records_table,
    format_rejected_rows,
    format_summary_text,
)
from inventrack.io_handler import load_inventory, save_inventory_csv, save_report_json
from inventrack.processor import (
    calculate_group_recap,
    calculate_summary,
    deduplicate_records,
    enrich_records,
    filter_records,
    group_records,
    search_records,
)
from inventrack.validators import VALID_DEDUP_STRATEGIES, VALID_GROUP_FIELDS, VALID_STATUSES

APP_NAME: Final[str] = "InvenTrack CLI"
APP_VERSION: Final[str] = "1.1.0"
APP_AUTHOR: Final[str] = "Robani Ichsan"
DEFAULT_INPUT_FILE: Final[str] = "data/input/inventaris_normal.csv"

EXIT_OK: Final[int] = 0
EXIT_DOMAIN_ERROR: Final[int] = 1
EXIT_INTERRUPTED: Final[int] = 130


def _resolve_default_input() -> str | None:
    """Kembalikan path dataset default bila tersedia di direktori kerja atau root proyek."""
    rel_path = Path(DEFAULT_INPUT_FILE)
    if rel_path.is_file():
        return DEFAULT_INPUT_FILE
    pkg_default = Path(__file__).resolve().parent.parent / DEFAULT_INPUT_FILE
    if pkg_default.is_file():
        try:
            return str(pkg_default.relative_to(Path.cwd()))
        except ValueError:
            return str(pkg_default)
    return None


def _resolve_cli_input(raw_input: str) -> str:
    """Gunakan fallback path relatif terhadap paket jika path default dipanggil dari luar root."""
    if raw_input == DEFAULT_INPUT_FILE and not Path(raw_input).is_file():
        resolved = _resolve_default_input()
        if resolved is not None:
            return resolved
    return raw_input


def _load_and_prepare(
    input_path: str,
    *,
    dedup_strategy: str = "latest",
    strict: bool = False,
) -> dict[str, Any]:
    """Muat file, bersihkan duplikat, perkaya field turunan, dan hitung ringkasan."""
    loaded = load_inventory(_resolve_cli_input(input_path), strict=strict)
    deduped, duplicates = deduplicate_records(loaded["records"], strategy=dedup_strategy)
    enriched = enrich_records(deduped)
    summary = calculate_summary(
        enriched,
        duplicates_removed=duplicates,
        rejected_rows=loaded["rejected_rows"],
    )
    return {
        "source_file": loaded["source_file"],
        "format": loaded["format"],
        "total_raw_rows": loaded["total_raw_rows"],
        "records": enriched,
        "duplicates": duplicates,
        "rejected_rows": loaded["rejected_rows"],
        "summary": summary,
    }


def _handle_analyze(args: argparse.Namespace) -> int:
    """Jalankan subcommand analyze: muat, deduplikasi, analisis, cetak & ekspor opsional."""
    prepared = _load_and_prepare(
        args.input,
        dedup_strategy=args.dedup_strategy,
        strict=args.strict,
    )
    print(f"Sumber Data : {prepared['source_file']} (format {prepared['format'].upper()})")
    print(f"Baris Mentah: {prepared['total_raw_rows']}")
    print(format_summary_text(prepared["summary"]))

    if args.output_csv:
        saved_csv = save_inventory_csv(prepared["records"], args.output_csv)
        print(f"Data bersih diekspor ke CSV : {saved_csv}")
    if args.output_json:
        report_payload = {
            "sumber_file": prepared["source_file"],
            "format_sumber": prepared["format"],
            "total_baris_mentah": prepared["total_raw_rows"],
            "strategi_deduplikasi": args.dedup_strategy,
            **prepared["summary"],
        }
        saved_json = save_report_json(report_payload, args.output_json)
        print(f"Laporan analisis diekspor ke JSON : {saved_json}")
    return EXIT_OK


def _handle_search(args: argparse.Namespace) -> int:
    """Jalankan subcommand search berdasarkan SKU atau kata kunci."""
    prepared = _load_and_prepare(args.input, dedup_strategy=args.dedup_strategy)
    matches = search_records(prepared["records"], args.query)
    print(f"Hasil pencarian untuk '{args.query}' ({len(matches)} ditemukan):")
    print(format_records_table(matches))
    return EXIT_OK


def _handle_filter(args: argparse.Namespace) -> int:
    """Jalankan subcommand filter multi-kriteria dan ekspor CSV opsional."""
    prepared = _load_and_prepare(args.input, dedup_strategy=args.dedup_strategy)
    filtered = filter_records(
        prepared["records"],
        kategori=args.kategori,
        lokasi=args.lokasi,
        status=args.status,
        min_harga=args.min_harga,
        max_harga=args.max_harga,
    )
    print(f"Hasil filter ({len(filtered)} dari {len(prepared['records'])} SKU):")
    print(format_records_table(filtered))
    if args.output_csv:
        saved_csv = save_inventory_csv(filtered, args.output_csv)
        print(f"Hasil filter diekspor ke CSV : {saved_csv}")
    return EXIT_OK


def _handle_group(args: argparse.Namespace) -> int:
    """Jalankan subcommand group dan tampilkan rekapitulasi per kelompok."""
    prepared = _load_and_prepare(args.input, dedup_strategy=args.dedup_strategy)
    grouped = group_records(prepared["records"], group_by=args.by)
    recap = calculate_group_recap(grouped)
    print(f"Rekapitulasi pengelompokan berdasarkan '{args.by}':")
    print(format_group_recap_table(recap, args.by))
    return EXIT_OK


def _handle_deduplicate(args: argparse.Namespace) -> int:
    """Jalankan subcommand deduplicate dan simpan hasilnya ke CSV baru."""
    prepared = _load_and_prepare(args.input, dedup_strategy=args.strategy)
    saved_csv = save_inventory_csv(prepared["records"], args.output_csv)
    print(
        f"Deduplikasi selesai (strategi='{args.strategy}'): "
        f"{len(prepared['records'])} SKU unik disimpan ke {saved_csv}."
    )
    print(format_duplicates_log(prepared["duplicates"]))
    if prepared["rejected_rows"]:
        print(format_rejected_rows(prepared["rejected_rows"]))
    return EXIT_OK


def prompt_optional_float(
    prompt_text: str,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> float | None:
    """Minta input angka float opsional secara defensif (enter untuk melewati)."""
    while True:
        raw = input_fn(prompt_text).strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            output_fn(f"Input '{raw}' bukan angka valid. Masukkan angka atau tekan Enter untuk lewati.")
            continue
        if not math.isfinite(value) or value < 0:
            output_fn("Nilai harus berupa angka finite non-negatif. Coba lagi.")
            continue
        return value


def run_interactive_session(
    initial_input: str | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> int:
    """Jalankan sesi menu CLI interaktif hingga pengguna memilih keluar.

    Args:
        initial_input: Path file opsional untuk langsung dimuat di awal sesi.
        input_fn: Fungsi pembaca input (default built-in input; dapat di-mock saat pengujian).
        output_fn: Fungsi pencetak output (default built-in print).

    Returns:
        Kode keluar 0 saat sesi berakhir normal.
    """
    state: dict[str, Any] | None = None
    output_fn(f"=== {APP_NAME} v{APP_VERSION} · crafted by {APP_AUTHOR} — Mode Interaktif ===")

    if initial_input:
        try:
            state = _load_and_prepare(initial_input)
            output_fn(f"Berhasil memuat '{state['source_file']}' ({len(state['records'])} SKU unik).")
        except InvenTrackError as exc:
            output_fn(f"[PERINGATAN] Gagal memuat file awal: {exc}")

    while True:
        active_file = state["source_file"] if state else "(belum ada file dimuat)"
        output_fn(f"\nFile aktif: {active_file}")
        output_fn("Menu:")
        output_fn("  1. Muat file data inventaris (CSV/JSON)")
        output_fn("  2. Tampilkan ringkasan analisis")
        output_fn("  3. Cari barang (SKU / kata kunci)")
        output_fn("  4. Filter barang")
        output_fn("  5. Kelompokkan & rekapitulasi")
        output_fn("  6. Ekspor CSV bersih & laporan JSON")
        output_fn("  0. Keluar")

        try:
            choice = input_fn("Pilih menu [0-6]: ").strip()
        except (EOFError, KeyboardInterrupt):
            output_fn("\nSesi interaktif dihentikan.")
            return EXIT_OK

        if choice == "0":
            output_fn(f"Terima kasih telah menggunakan {APP_NAME}.")
            return EXIT_OK

        if choice not in {"1", "2", "3", "4", "5", "6"}:
            output_fn(f"Pilihan '{choice}' tidak dikenali. Silakan pilih angka 0 sampai 6.")
            continue

        if choice == "1":
            path_input = input_fn("Masukkan path file (.csv/.json): ").strip()
            if not path_input:
                path_input = _resolve_default_input() or DEFAULT_INPUT_FILE
            strategy = input_fn("Strategi duplikat [latest/first] (default: latest): ").strip() or "latest"
            try:
                state = _load_and_prepare(path_input, dedup_strategy=strategy)
                output_fn(
                    f"Berhasil memuat {len(state['records'])} SKU unik "
                    f"(duplikat dihapus: {len(state['duplicates'])}, "
                    f"baris ditolak: {len(state['rejected_rows'])})."
                )
            except InvenTrackError as exc:
                output_fn(f"[ERROR] {exc}")
            continue

        if state is None:
            output_fn("[PERINGATAN] Belum ada file dimuat. Pilih menu 1 terlebih dahulu.")
            continue

        if choice == "2":
            output_fn(format_summary_text(state["summary"]))
        elif choice == "3":
            query = input_fn("Masukkan SKU atau kata kunci pencarian: ")
            try:
                matches = search_records(state["records"], query)
                output_fn(f"Ditemukan {len(matches)} barang:")
                output_fn(format_records_table(matches))
            except InvalidUserInputError as exc:
                output_fn(f"[ERROR] {exc}")
        elif choice == "4":
            kategori = input_fn("Filter kategori (kosongkan jika semua): ").strip() or None
            lokasi = input_fn("Filter gudang (kosongkan jika semua): ").strip() or None
            status = (
                input_fn("Filter status [HABIS/KRITIS/AMAN/BERLEBIH] (kosongkan jika semua): ").strip()
                or None
            )
            min_harga = prompt_optional_float(
                "Harga minimum (kosongkan jika tanpa batas): ",
                input_fn=input_fn,
                output_fn=output_fn,
            )
            max_harga = prompt_optional_float(
                "Harga maksimum (kosongkan jika tanpa batas): ",
                input_fn=input_fn,
                output_fn=output_fn,
            )
            try:
                filtered = filter_records(
                    state["records"],
                    kategori=kategori,
                    lokasi=lokasi,
                    status=status,
                    min_harga=min_harga,
                    max_harga=max_harga,
                )
                output_fn(f"Hasil filter ({len(filtered)} barang):")
                output_fn(format_records_table(filtered))
            except InvalidUserInputError as exc:
                output_fn(f"[ERROR] {exc}")
        elif choice == "5":
            group_by = (
                input_fn("Kelompokkan berdasarkan [kategori/lokasi_gudang/status_stok/pemasok]: ").strip()
                or "kategori"
            )
            try:
                grouped = group_records(state["records"], group_by=group_by)
                recap = calculate_group_recap(grouped)
                output_fn(format_group_recap_table(recap, group_by))
            except InvalidUserInputError as exc:
                output_fn(f"[ERROR] {exc}")
        elif choice == "6":
            csv_out = input_fn("Path output CSV bersih (kosongkan untuk lewati): ").strip()
            json_out = input_fn("Path output laporan JSON (kosongkan untuk lewati): ").strip()
            try:
                if csv_out:
                    saved_csv = save_inventory_csv(state["records"], csv_out)
                    output_fn(f"CSV disimpan ke: {saved_csv}")
                if json_out:
                    payload = {
                        "sumber_file": state["source_file"],
                        "format_sumber": state["format"],
                        "total_baris_mentah": state["total_raw_rows"],
                        **state["summary"],
                    }
                    saved_json = save_report_json(payload, json_out)
                    output_fn(f"JSON disimpan ke: {saved_json}")
                if not csv_out and not json_out:
                    output_fn("Tidak ada file yang diekspor.")
            except InvenTrackError as exc:
                output_fn(f"[ERROR] {exc}")


def build_parser() -> argparse.ArgumentParser:
    """Bangun parser argumen CLI utama beserta seluruh subcommand-nya."""
    parser = argparse.ArgumentParser(
        prog="inventrack",
        description=f"{APP_NAME} — Deterministic Warehouse Inventory Validation & Restock Analytics.",
        epilog=f"Crafted by {APP_AUTHOR} · Zero External Dependencies (Python Standard Library)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"{APP_NAME} {APP_VERSION} (by {APP_AUTHOR})",
        help="Tampilkan versi aplikasi dan informasi pembuat.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Daftar perintah yang tersedia")

    p_analyze = subparsers.add_parser("analyze", help="Muat, validasi, deduplikasi, dan analisis data.")
    p_analyze.add_argument(
        "--input",
        default=DEFAULT_INPUT_FILE,
        help=f"Path file input (.csv atau .json, default: {DEFAULT_INPUT_FILE}).",
    )
    p_analyze.add_argument("--output-csv", help="Path file CSV bersih keluaran (opsional).")
    p_analyze.add_argument("--output-json", help="Path file laporan JSON keluaran (opsional).")
    p_analyze.add_argument(
        "--dedup-strategy",
        default="latest",
        choices=sorted(VALID_DEDUP_STRATEGIES),
        help="Strategi penanganan duplikat SKU (default: latest).",
    )
    p_analyze.add_argument(
        "--strict",
        action="store_true",
        help="Hentikan proses jika ada satu saja baris input tidak valid.",
    )

    p_search = subparsers.add_parser("search", help="Cari barang berdasarkan SKU atau kata kunci.")
    p_search.add_argument(
        "--input",
        default=DEFAULT_INPUT_FILE,
        help=f"Path file input (.csv atau .json, default: {DEFAULT_INPUT_FILE}).",
    )
    p_search.add_argument("--query", required=True, help="Kata kunci SKU, nama, kategori, pemasok, atau gudang.")
    p_search.add_argument(
        "--dedup-strategy",
        default="latest",
        choices=sorted(VALID_DEDUP_STRATEGIES),
        help="Strategi penanganan duplikat SKU (default: latest).",
    )

    p_filter = subparsers.add_parser("filter", help="Filter barang berdasarkan satu atau lebih kriteria.")
    p_filter.add_argument(
        "--input",
        default=DEFAULT_INPUT_FILE,
        help=f"Path file input (.csv atau .json, default: {DEFAULT_INPUT_FILE}).",
    )
    p_filter.add_argument("--kategori", help="Filter berdasarkan kategori.")
    p_filter.add_argument("--lokasi", help="Filter berdasarkan kode gudang.")
    p_filter.add_argument(
        "--status",
        choices=sorted(VALID_STATUSES),
        help="Filter berdasarkan status stok.",
    )
    p_filter.add_argument("--min-harga", type=float, help="Batas minimum harga satuan.")
    p_filter.add_argument("--max-harga", type=float, help="Batas maksimum harga satuan.")
    p_filter.add_argument("--output-csv", help="Simpan hasil filter ke file CSV (opsional).")
    p_filter.add_argument(
        "--dedup-strategy",
        default="latest",
        choices=sorted(VALID_DEDUP_STRATEGIES),
        help="Strategi penanganan duplikat SKU (default: latest).",
    )

    p_group = subparsers.add_parser("group", help="Kelompokkan data dan tampilkan rekapitulasi.")
    p_group.add_argument(
        "--input",
        default=DEFAULT_INPUT_FILE,
        help=f"Path file input (.csv atau .json, default: {DEFAULT_INPUT_FILE}).",
    )
    p_group.add_argument(
        "--by",
        default="kategori",
        choices=sorted(VALID_GROUP_FIELDS),
        help="Atribut pengelompokan (default: kategori).",
    )
    p_group.add_argument(
        "--dedup-strategy",
        default="latest",
        choices=sorted(VALID_DEDUP_STRATEGIES),
        help="Strategi penanganan duplikat SKU (default: latest).",
    )

    p_dedup = subparsers.add_parser("deduplicate", help="Bersihkan duplikasi SKU dan ekspor ke CSV.")
    p_dedup.add_argument(
        "--input",
        default=DEFAULT_INPUT_FILE,
        help=f"Path file input (.csv atau .json, default: {DEFAULT_INPUT_FILE}).",
    )
    p_dedup.add_argument("--output-csv", required=True, help="Path file CSV keluaran hasil deduplikasi.")
    p_dedup.add_argument(
        "--strategy",
        default="latest",
        choices=sorted(VALID_DEDUP_STRATEGIES),
        help="Strategi deduplikasi (default: latest).",
    )

    p_inter = subparsers.add_parser("interactive", help="Jalankan mode menu interaktif di terminal.")
    p_inter.add_argument("--input", help="Path file input awal yang otomatis dimuat (opsional).")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point utama InvenTrack CLI.

    Args:
        argv: Daftar argumen command-line (default None mengambil sys.argv[1:]).

    Returns:
        Exit code integer (0 sukses, 1 error domain/input, 130 interrupt pengguna).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "analyze": _handle_analyze,
        "search": _handle_search,
        "filter": _handle_filter,
        "group": _handle_group,
        "deduplicate": _handle_deduplicate,
    }

    try:
        if args.command is None:
            return run_interactive_session(initial_input=_resolve_default_input())
        if args.command == "interactive":
            return run_interactive_session(initial_input=args.input or _resolve_default_input())
        handler = handlers[args.command]
        return handler(args)
    except InvenTrackError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_DOMAIN_ERROR
    except KeyboardInterrupt:
        print("\nOperasi dibatalkan oleh pengguna.", file=sys.stderr)
        return EXIT_INTERRUPTED
