"""Suite unit test, integration test, dan regression test untuk InvenTrack CLI."""

from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import inventrack
from inventrack.cli import main, run_interactive_session
from inventrack.exceptions import (
    DataFileNotFoundError,
    InvalidDataFormatError,
    InvalidUserInputError,
    InvenTrackError,
    RecordValidationError,
    UnsupportedFormatError,
)
from inventrack.formatter import format_currency_idr, format_summary_text
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
from inventrack.validators import (
    normalize_sku,
    normalize_text,
    parse_non_negative_float,
    parse_non_negative_int,
    validate_and_normalize_record,
    validate_iso_date,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_INPUT_DIR = PROJECT_ROOT / "data" / "input"


class TestValidators(unittest.TestCase):
    """Pengujian unit untuk fungsi validasi dan normalisasi field."""

    def test_normalize_sku_valid_and_invalid(self) -> None:
        self.assertEqual(normalize_sku("  sku-019 "), "SKU-019")
        self.assertEqual(normalize_sku("Abc-123"), "ABC-123")
        for bad_value in ("", "   ", None, True, {"a": 1}, ["x"]):
            with self.assertRaises(ValueError):
                normalize_sku(bad_value)

    def test_normalize_text_modes(self) -> None:
        self.assertEqual(normalize_text("  bor   cordless  18v ", "nama_barang"), "bor cordless 18v")
        self.assertEqual(
            normalize_text("  keselamatan   kerja ", "kategori", title_case=True),
            "Keselamatan Kerja",
        )
        self.assertEqual(
            normalize_text(" gudang-c ", "lokasi_gudang", upper_case=True),
            "GUDANG-C",
        )
        with self.assertRaises(ValueError):
            normalize_text("   ", "nama_barang")
        with self.assertRaises(ValueError):
            normalize_text(False, "nama_barang")

    def test_parse_non_negative_int_rejects_bad_values(self) -> None:
        self.assertEqual(parse_non_negative_int(0, "stok"), 0)
        self.assertEqual(parse_non_negative_int("42", "stok"), 42)
        self.assertEqual(parse_non_negative_int(10.0, "stok"), 10)
        for bad in (-1, "-5", "4.5", 4.5, "", "abc", None, True, False, float("nan")):
            with self.assertRaises(ValueError):
                parse_non_negative_int(bad, "stok")

    def test_parse_non_negative_float_rejects_bad_values(self) -> None:
        self.assertEqual(parse_non_negative_float(12500000.5, "harga_satuan"), 12500000.5)
        self.assertEqual(parse_non_negative_float("15000.346", "harga_satuan"), 15000.35)
        for bad in (-0.01, "-100", "gratis", "", None, True, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                parse_non_negative_float(bad, "harga_satuan")

    def test_validate_iso_date_strict_format_and_calendar(self) -> None:
        self.assertEqual(validate_iso_date(" 2026-11-18 "), "2026-11-18")
        for bad_date in ("2026-02-30", "2026-2-5", "18-11-2026", "2026/11/18", "", None, 20261118):
            with self.assertRaises(ValueError):
                validate_iso_date(bad_date)

    def test_validate_and_normalize_record(self) -> None:
        raw = {
            "sku": " sku-100 ",
            "nama_barang": "  Helm   Proyek  ",
            "kategori": "keselamatan kerja",
            "lokasi_gudang": "gudang-a",
            "stok": "12",
            "stok_minimum": "5",
            "harga_satuan": "85000",
            "pemasok": " PT  Aman ",
            "tanggal_update": "2026-11-10",
        }
        cleaned = validate_and_normalize_record(raw, row_number=2)
        self.assertEqual(cleaned["sku"], "SKU-100")
        self.assertEqual(cleaned["nama_barang"], "Helm Proyek")
        self.assertEqual(cleaned["kategori"], "Keselamatan Kerja")
        self.assertEqual(cleaned["lokasi_gudang"], "GUDANG-A")
        self.assertEqual(cleaned["stok"], 12)
        self.assertEqual(cleaned["harga_satuan"], 85000.0)

        incomplete = dict(raw)
        incomplete.pop("pemasok")
        with self.assertRaises(RecordValidationError) as ctx:
            validate_and_normalize_record(incomplete, row_number=7)
        self.assertEqual(ctx.exception.row_number, 7)


class TestProcessor(unittest.TestCase):
    """Pengujian unit untuk logika bisnis, struktur data, dan analisis inventaris."""

    def setUp(self) -> None:
        self.sample_records = [
            {
                "sku": "SKU-001",
                "nama_barang": "Scanner Barcode",
                "kategori": "Elektronik",
                "lokasi_gudang": "GUDANG-A",
                "stok": 0,
                "stok_minimum": 5,
                "harga_satuan": 500000.0,
                "pemasok": "PT Tech",
                "tanggal_update": "2026-11-01",
            },
            {
                "sku": "SKU-002",
                "nama_barang": "Printer Thermal",
                "kategori": "Elektronik",
                "lokasi_gudang": "GUDANG-B",
                "stok": 3,
                "stok_minimum": 5,
                "harga_satuan": 1000000.0,
                "pemasok": "PT Tech",
                "tanggal_update": "2026-11-02",
            },
            {
                "sku": "SKU-003",
                "nama_barang": "Lakban Bening",
                "kategori": "Kemasan",
                "lokasi_gudang": "GUDANG-B",
                "stok": 100,
                "stok_minimum": 10,
                "harga_satuan": 10000.0,
                "pemasok": "PT Kemas",
                "tanggal_update": "2026-11-03",
            },
        ]

    def test_classify_stock_status_including_boundaries(self) -> None:
        self.assertEqual(classify_stock_status(0, 5), "HABIS")
        self.assertEqual(classify_stock_status(0, 0), "HABIS")
        self.assertEqual(classify_stock_status(5, 5), "KRITIS")
        self.assertEqual(classify_stock_status(20, 4), "AMAN")
        self.assertEqual(classify_stock_status(15, 0), "AMAN")
        self.assertEqual(classify_stock_status(21, 4), "BERLEBIH")

    def test_calculate_restock_recommendation(self) -> None:
        self.assertEqual(calculate_restock_recommendation(0, 5, "HABIS"), 10)
        self.assertEqual(calculate_restock_recommendation(3, 5, "KRITIS"), 7)
        self.assertEqual(calculate_restock_recommendation(10, 5, "AMAN"), 0)
        self.assertEqual(calculate_restock_recommendation(50, 5, "BERLEBIH"), 0)

    def test_enrich_records_does_not_mutate_input(self) -> None:
        enriched = enrich_records(self.sample_records)
        self.assertNotIn("status_stok", self.sample_records[0])
        self.assertEqual(enriched[0]["status_stok"], "HABIS")
        self.assertEqual(enriched[0]["nilai_stok"], 0.0)
        self.assertEqual(enriched[0]["rekomendasi_restock"], 10)
        self.assertEqual(enriched[1]["status_stok"], "KRITIS")
        self.assertEqual(enriched[1]["nilai_stok"], 3000000.0)
        self.assertEqual(enriched[2]["status_stok"], "BERLEBIH")

    def test_deduplicate_latest_and_first_with_reversed_dates(self) -> None:
        records = [
            {**self.sample_records[0], "sku": "SKU-011", "stok": 18, "tanggal_update": "2026-11-12"},
            {**self.sample_records[0], "sku": "SKU-011", "stok": 2, "tanggal_update": "2026-10-01"},
            {**self.sample_records[1], "sku": "SKU-002", "stok": 3, "tanggal_update": "2026-10-05"},
            {**self.sample_records[1], "sku": "SKU-002", "stok": 9, "tanggal_update": "2026-11-20"},
        ]
        latest_res, latest_dups = deduplicate_records(records, strategy="latest")
        self.assertEqual(len(latest_res), 2)
        self.assertEqual(latest_res[0]["stok"], 18)
        self.assertEqual(latest_res[1]["stok"], 9)
        self.assertEqual(len(latest_dups), 2)

        first_res, first_dups = deduplicate_records(records, strategy="first")
        self.assertEqual(first_res[0]["stok"], 18)
        self.assertEqual(first_res[1]["stok"], 3)
        self.assertEqual(len(first_dups), 2)

        with self.assertRaises(InvalidUserInputError):
            deduplicate_records(records, strategy="newest")

    def test_search_and_sku_index(self) -> None:
        enriched = enrich_records(self.sample_records)
        index = build_sku_index(enriched)
        self.assertIn("SKU-002", index)
        self.assertEqual(len(search_records(enriched, "sku-002")), 1)
        self.assertEqual(len(search_records(enriched, "PT Tech")), 2)
        self.assertEqual(search_records(enriched, "tidak-ada-barang"), [])
        with self.assertRaises(InvalidUserInputError):
            search_records(enriched, "   ")

    def test_filter_records_single_multi_and_validation(self) -> None:
        enriched = enrich_records(self.sample_records)
        self.assertEqual(len(filter_records(enriched, status="KRITIS")), 1)
        self.assertEqual(
            len(
                filter_records(
                    enriched,
                    kategori="elektronik",
                    lokasi="gudang-b",
                    min_harga=900000,
                    max_harga=1500000,
                )
            ),
            1,
        )
        with self.assertRaises(InvalidUserInputError):
            filter_records(enriched, status="RUSAK")
        with self.assertRaises(InvalidUserInputError):
            filter_records(enriched, min_harga=-10)
        with self.assertRaises(InvalidUserInputError):
            filter_records(enriched, min_harga=50000, max_harga=10000)

    def test_group_extract_unique_and_recap(self) -> None:
        enriched = enrich_records(self.sample_records)
        grouped = group_records(enriched, "kategori")
        self.assertEqual(list(grouped.keys()), ["Elektronik", "Kemasan"])
        recap = calculate_group_recap(grouped)
        self.assertEqual(recap["Elektronik"]["jumlah_sku"], 2)
        self.assertEqual(recap["Elektronik"]["jumlah_kritis_atau_habis"], 2)
        meta = extract_unique_metadata(enriched)
        self.assertEqual(meta["kategori"], {"Elektronik", "Kemasan"})
        self.assertEqual(meta["lokasi_gudang"], {"GUDANG-A", "GUDANG-B"})

        with self.assertRaises(InvalidUserInputError):
            group_records(enriched, "harga_satuan")

        empty_recap = calculate_group_recap({"Kosong": []})
        self.assertEqual(empty_recap["Kosong"]["rata_rata_harga"], 0.0)

    def test_calculate_summary_normal_and_empty_edge_case(self) -> None:
        enriched = enrich_records(self.sample_records)
        summary = calculate_summary(enriched)
        self.assertEqual(summary["ringkasan_umum"]["total_sku_unik"], 3)
        self.assertEqual(summary["ringkasan_umum"]["total_valuasi_idr"], 4000000.0)
        self.assertEqual(summary["distribusi_status"]["HABIS"], 1)
        self.assertEqual(summary["distribusi_status"]["KRITIS"], 1)
        self.assertEqual(len(summary["daftar_perlu_restock"]), 2)

        empty_summary = calculate_summary([])
        self.assertEqual(empty_summary["ringkasan_umum"]["total_sku_unik"], 0)
        self.assertEqual(empty_summary["ringkasan_umum"]["rata_rata_harga_satuan_idr"], 0.0)
        self.assertIsNone(empty_summary["ringkasan_umum"]["item_nilai_tertinggi"])
        self.assertEqual(
            empty_summary["distribusi_status"],
            {"HABIS": 0, "KRITIS": 0, "AMAN": 0, "BERLEBIH": 0},
        )
        self.assertIn("Total SKU Unik          : 0", format_summary_text(empty_summary))


class TestIOHandlerAndDatasets(unittest.TestCase):
    """Pengujian pembacaan/penulisan CSV & JSON serta validasi dataset proyek."""

    def test_load_normal_dataset_end_to_end(self) -> None:
        loaded = load_inventory(DATA_INPUT_DIR / "inventaris_normal.csv")
        self.assertEqual(loaded["total_raw_rows"], 28)
        self.assertEqual(loaded["rejected_rows"], [])
        deduped, dups = deduplicate_records(loaded["records"], strategy="latest")
        self.assertEqual(len(deduped), 25)
        self.assertEqual(len(dups), 3)
        enriched = enrich_records(deduped)
        summary = calculate_summary(enriched, duplicates_removed=dups)
        self.assertEqual(summary["distribusi_status"]["HABIS"], 3)
        self.assertEqual(summary["distribusi_status"]["KRITIS"], 6)
        self.assertEqual(summary["distribusi_status"]["AMAN"], 12)
        self.assertEqual(summary["distribusi_status"]["BERLEBIH"], 4)

    def test_load_edge_empty_csv(self) -> None:
        loaded = load_inventory(DATA_INPUT_DIR / "inventaris_edge_empty.csv")
        self.assertEqual(loaded["total_raw_rows"], 0)
        self.assertEqual(loaded["records"], [])
        self.assertEqual(loaded["rejected_rows"], [])

    def test_load_edge_dirty_bom_csv_non_strict_and_strict(self) -> None:
        dirty_path = DATA_INPUT_DIR / "inventaris_edge_dirty.csv"
        loaded = load_inventory(dirty_path, strict=False)
        self.assertEqual(loaded["total_raw_rows"], 8)
        self.assertEqual(len(loaded["records"]), 3)
        self.assertEqual(len(loaded["rejected_rows"]), 5)
        self.assertEqual(loaded["records"][0]["sku"], "SKU-901")

        enriched = enrich_records(loaded["records"])
        self.assertEqual(enriched[0]["status_stok"], "HABIS")
        self.assertEqual(enriched[1]["status_stok"], "AMAN")
        self.assertEqual(enriched[2]["status_stok"], "KRITIS")

        with self.assertRaises(InvalidDataFormatError):
            load_inventory(dirty_path, strict=True)

    def test_load_edge_unicode_json(self) -> None:
        loaded = load_inventory(DATA_INPUT_DIR / "inventaris_edge_unicode.json")
        self.assertEqual(loaded["format"], "json")
        self.assertEqual(loaded["total_raw_rows"], 4)
        self.assertEqual(loaded["rejected_rows"], [])
        deduped, dups = deduplicate_records(loaded["records"], strategy="latest")
        self.assertEqual(len(deduped), 3)
        self.assertEqual(len(dups), 1)
        self.assertEqual(deduped[0]["stok"], 8)
        self.assertIn("Adaptér", deduped[0]["nama_barang"])

    def test_error_conditions_for_files_and_formats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with self.assertRaises(DataFileNotFoundError):
                load_inventory(tmp / "tidak_ada.csv")
            with self.assertRaises(DataFileNotFoundError):
                load_inventory(tmp)

            txt_file = tmp / "notes.txt"
            txt_file.write_text("hello", encoding="utf-8")
            with self.assertRaises(UnsupportedFormatError):
                load_inventory(txt_file)

            bad_header_csv = tmp / "bad_header.csv"
            bad_header_csv.write_text("sku,nama_barang\nSKU-1,Mouse\n", encoding="utf-8")
            with self.assertRaises(InvalidDataFormatError):
                load_inventory(bad_header_csv)

            empty_file_csv = tmp / "truly_empty.csv"
            empty_file_csv.write_text("", encoding="utf-8")
            with self.assertRaises(InvalidDataFormatError):
                load_inventory(empty_file_csv)

            bad_json = tmp / "broken.json"
            bad_json.write_text("{broken json", encoding="utf-8")
            with self.assertRaises(InvalidDataFormatError):
                load_inventory(bad_json)

            wrong_root_json = tmp / "wrong_root.json"
            wrong_root_json.write_text(json.dumps({"not_items": []}), encoding="utf-8")
            with self.assertRaises(InvalidDataFormatError):
                load_inventory(wrong_root_json)

            wrapped_json = tmp / "wrapped.json"
            wrapped_json.write_text(
                json.dumps({"items": ["bukan_object"]}),
                encoding="utf-8",
            )
            res = load_inventory(wrapped_json)
            self.assertEqual(len(res["records"]), 0)
            self.assertEqual(len(res["rejected_rows"]), 1)

    def test_save_csv_and_json_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            csv_out = tmp / "nested" / "out.csv"
            json_out = tmp / "nested" / "report.json"

            save_inventory_csv([], csv_out)
            with csv_out.open(encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(len(rows), 1)
            self.assertIn("nilai_stok", rows[0])

            save_report_json({"status": "ok", "jumlah": 3}, json_out)
            parsed = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertEqual(parsed, {"status": "ok", "jumlah": 3})


class TestCLIAndDebuggingRegressions(unittest.TestCase):
    """Pengujian integrasi CLI dan regression test untuk skenario debugging."""

    def test_cli_subcommands_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out_csv = tmp / "clean.csv"
            out_json = tmp / "summary.json"
            out_filter = tmp / "kritis.csv"
            out_dedup = tmp / "dedup.csv"

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        "analyze",
                        "--input",
                        str(DATA_INPUT_DIR / "inventaris_normal.csv"),
                        "--output-csv",
                        str(out_csv),
                        "--output-json",
                        str(out_json),
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertTrue(out_csv.exists())
            self.assertTrue(out_json.exists())

            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "search",
                            "--input",
                            str(DATA_INPUT_DIR / "inventaris_normal.csv"),
                            "--query",
                            "Scanner",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "filter",
                            "--input",
                            str(DATA_INPUT_DIR / "inventaris_normal.csv"),
                            "--status",
                            "KRITIS",
                            "--output-csv",
                            str(out_filter),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "group",
                            "--input",
                            str(DATA_INPUT_DIR / "inventaris_normal.csv"),
                            "--by",
                            "lokasi_gudang",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "deduplicate",
                            "--input",
                            str(DATA_INPUT_DIR / "inventaris_normal.csv"),
                            "--output-csv",
                            str(out_dedup),
                            "--strategy",
                            "first",
                        ]
                    ),
                    0,
                )

            self.assertTrue(out_filter.exists())
            self.assertTrue(out_dedup.exists())

    def test_cli_returns_nonzero_on_missing_file_and_invalid_filter(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["analyze", "--input", "/tmp/file_pasti_tidak_ada_12345.csv"])
        self.assertEqual(rc, 1)
        self.assertIn("[ERROR]", err.getvalue())

        err2 = io.StringIO()
        with redirect_stderr(err2):
            rc2 = main(
                [
                    "filter",
                    "--input",
                    str(DATA_INPUT_DIR / "inventaris_normal.csv"),
                    "--min-harga",
                    "500000",
                    "--max-harga",
                    "10000",
                ]
            )
        self.assertEqual(rc2, 1)
        self.assertIn("Rentang harga tidak valid", err2.getvalue())

    def test_interactive_session_with_defensive_handling(self) -> None:
        answers = iter(
            [
                "9",
                "2",
                "1",
                str(DATA_INPUT_DIR / "inventaris_normal.csv"),
                "latest",
                "3",
                "SKU-001",
                "4",
                "",
                "",
                "HABIS",
                "bukan_angka",
                "nan",
                "100000",
                "",
                "0",
            ]
        )
        outputs: list[str] = []
        rc = run_interactive_session(
            input_fn=lambda _prompt: next(answers),
            output_fn=outputs.append,
        )
        self.assertEqual(rc, 0)
        joined = "\n".join(outputs)
        self.assertIn("tidak dikenali", joined)
        self.assertIn("Belum ada file dimuat", joined)
        self.assertIn("Berhasil memuat 25 SKU unik", joined)
        self.assertIn("bukan angka valid", joined)
        self.assertIn("angka finite non-negatif", joined)
        self.assertIn("Scanner Barcode Wireless 2D", joined)

    def test_csv_extra_columns_isolated_in_rejected_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "extra_cols.csv"
            csv_path.write_text(
                "sku,nama_barang,kategori,lokasi_gudang,stok,stok_minimum,harga_satuan,pemasok,tanggal_update\n"
                "SKU-1,Mouse,Elektronik,GUDANG-A,5,2,50000,PT A,2026-11-01,KOLOM_LIAR\n",
                encoding="utf-8",
            )
            res = load_inventory(csv_path, strict=False)
            self.assertEqual(len(res["records"]), 0)
            self.assertEqual(len(res["rejected_rows"]), 1)
            self.assertIn("melebihi definisi header", res["rejected_rows"][0]["reason"])

    def test_formatter_currency_idr(self) -> None:
        self.assertEqual(format_currency_idr(1250000), "Rp1.250.000")
        self.assertEqual(format_currency_idr(12500000.5), "Rp12.500.000,50")
        self.assertEqual(format_currency_idr(0), "Rp0")

    def test_regression_scenario_1_empty_dataset_and_reversed_sku_dedup(self) -> None:
        """Regression test untuk Skenario Debugging 1: dataset kosong & urutan tanggal terbalik."""
        empty_summary = calculate_summary([])
        self.assertEqual(empty_summary["ringkasan_umum"]["total_sku_unik"], 0)
        self.assertEqual(empty_summary["ringkasan_umum"]["rata_rata_harga_satuan_idr"], 0.0)

        loaded = load_inventory(DATA_INPUT_DIR / "inventaris_normal.csv")
        deduped, _ = deduplicate_records(loaded["records"], strategy="latest")
        sku_map = build_sku_index(deduped)
        self.assertEqual(sku_map["SKU-011"]["tanggal_update"], "2026-11-12")
        self.assertEqual(sku_map["SKU-011"]["stok"], 18)
        self.assertEqual(sku_map["SKU-019"]["tanggal_update"], "2026-11-18")
        self.assertEqual(sku_map["SKU-019"]["stok"], 24)

    def test_regression_scenario_2_utf8_bom_and_row_isolation(self) -> None:
        """Regression test untuk Skenario Debugging 2: CSV UTF-8 BOM & isolasi baris error."""
        loaded = load_inventory(DATA_INPUT_DIR / "inventaris_edge_dirty.csv", strict=False)
        self.assertEqual(len(loaded["records"]), 3)
        self.assertEqual(len(loaded["rejected_rows"]), 5)
        reasons = " | ".join(item["reason"] for item in loaded["rejected_rows"])
        self.assertIn("sku", reasons.lower())
        self.assertIn("negatif", reasons.lower())
        self.assertIn("2026-02-30", reasons)

    def test_package_metadata_and_version_flag(self) -> None:
        self.assertEqual(inventrack.__author__, "Robani Ichsan")
        self.assertEqual(inventrack.__license__, "MIT")
        self.assertEqual(inventrack.__version__, "1.1.0")

        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("1.1.0", out.getvalue())
        self.assertIn("Robani Ichsan", out.getvalue())

    def test_record_validation_error_tracks_offending_field(self) -> None:
        bad_row = {
            "sku": "SKU-777",
            "nama_barang": "Sensor Optik",
            "kategori": "Elektronik",
            "lokasi_gudang": "GUDANG-A",
            "stok": "-3",
            "stok_minimum": "2",
            "harga_satuan": "50000",
            "pemasok": "PT Presisi",
            "tanggal_update": "2026-11-10",
        }
        with self.assertRaises(RecordValidationError) as ctx:
            validate_and_normalize_record(bad_row, row_number=4)
        self.assertEqual(ctx.exception.row_number, 4)
        self.assertEqual(ctx.exception.field_name, "stok")

    def test_atomic_json_save_cleans_up_temp_file_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "report.json"
            with self.assertRaises(InvenTrackError):
                save_report_json({"bad": {1, 2, 3}}, target)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(tmpdir).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
