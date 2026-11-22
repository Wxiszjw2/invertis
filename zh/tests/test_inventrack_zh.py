"""InvenTrack CLI（简体中文版）单元测试、集成测试与回归测试套件。"""

from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ZH_ROOT = Path(__file__).resolve().parent.parent
if str(ZH_ROOT) not in sys.path:
    sys.path.insert(0, str(ZH_ROOT))

import inventrack_zh
from inventrack_zh.cli import main, run_interactive_session
from inventrack_zh.exceptions import (
    DataFileNotFoundError,
    InvalidDataFormatError,
    InvalidUserInputError,
    InvenTrackError,
    RecordValidationError,
    UnsupportedFormatError,
)
from inventrack_zh.formatter import (
    format_currency_idr,
    format_records_table,
    format_summary_text,
)
from inventrack_zh.io_handler import load_inventory, save_inventory_csv, save_report_json
from inventrack_zh.processor import (
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
from inventrack_zh.validators import (
    normalize_sku,
    normalize_text,
    parse_non_negative_float,
    parse_non_negative_int,
    validate_and_normalize_record,
    validate_iso_date,
)

DATA_INPUT_DIR = ZH_ROOT / "data" / "input"


class TestValidatorsZh(unittest.TestCase):
    """字段校验与数据规范化单元测试。"""

    def test_normalize_sku_valid_and_invalid(self) -> None:
        self.assertEqual(normalize_sku("  sku-019 "), "SKU-019")
        self.assertEqual(normalize_sku("Abc-123"), "ABC-123")
        for bad_value in ("", "   ", None, True, {"a": 1}, ["x"]):
            with self.assertRaises(ValueError):
                normalize_sku(bad_value)

    def test_normalize_text_modes(self) -> None:
        self.assertEqual(normalize_text("  无线   扫描器  ", "nama_barang"), "无线 扫描器")
        self.assertEqual(
            normalize_text("  safety   gear ", "kategori", title_case=True),
            "Safety Gear",
        )
        self.assertEqual(
            normalize_text(" a号仓 ", "lokasi_gudang", upper_case=True),
            "A号仓",
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
        for bad in (-0.01, "-100", "免费", "", None, True, float("inf"), float("nan")):
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
            "nama_barang": "  国标   安全帽  ",
            "kategori": "安全防护",
            "lokasi_gudang": "a号仓",
            "stok": "12",
            "stok_minimum": "5",
            "harga_satuan": "85000",
            "pemasok": " 安捷防护 ",
            "tanggal_update": "2026-11-10",
        }
        cleaned = validate_and_normalize_record(raw, row_number=2)
        self.assertEqual(cleaned["sku"], "SKU-100")
        self.assertEqual(cleaned["nama_barang"], "国标 安全帽")
        self.assertEqual(cleaned["kategori"], "安全防护")
        self.assertEqual(cleaned["lokasi_gudang"], "A号仓")
        self.assertEqual(cleaned["stok"], 12)
        self.assertEqual(cleaned["harga_satuan"], 85000.0)

        incomplete = dict(raw)
        incomplete.pop("pemasok")
        with self.assertRaises(RecordValidationError) as ctx:
            validate_and_normalize_record(incomplete, row_number=7)
        self.assertEqual(ctx.exception.row_number, 7)


class TestProcessorZh(unittest.TestCase):
    """核心库存业务逻辑、数据结构与分析函数单元测试。"""

    def setUp(self) -> None:
        self.sample_records = [
            {
                "sku": "SKU-001",
                "nama_barang": "条码扫描器",
                "kategori": "电子设备",
                "lokasi_gudang": "A号仓",
                "stok": 0,
                "stok_minimum": 5,
                "harga_satuan": 500000.0,
                "pemasok": "科技公司",
                "tanggal_update": "2026-11-01",
            },
            {
                "sku": "SKU-002",
                "nama_barang": "热敏打印机",
                "kategori": "电子设备",
                "lokasi_gudang": "B号仓",
                "stok": 3,
                "stok_minimum": 5,
                "harga_satuan": 1000000.0,
                "pemasok": "科技公司",
                "tanggal_update": "2026-11-02",
            },
            {
                "sku": "SKU-003",
                "nama_barang": "透明胶带",
                "kategori": "包装耗材",
                "lokasi_gudang": "B号仓",
                "stok": 100,
                "stok_minimum": 10,
                "harga_satuan": 10000.0,
                "pemasok": "包装公司",
                "tanggal_update": "2026-11-03",
            },
        ]

    def test_classify_stock_status_including_boundaries(self) -> None:
        self.assertEqual(classify_stock_status(0, 5), "缺货")
        self.assertEqual(classify_stock_status(0, 0), "缺货")
        self.assertEqual(classify_stock_status(5, 5), "预警")
        self.assertEqual(classify_stock_status(20, 4), "正常")
        self.assertEqual(classify_stock_status(15, 0), "正常")
        self.assertEqual(classify_stock_status(21, 4), "积压")

    def test_calculate_restock_recommendation(self) -> None:
        self.assertEqual(calculate_restock_recommendation(0, 5, "缺货"), 10)
        self.assertEqual(calculate_restock_recommendation(3, 5, "预警"), 7)
        self.assertEqual(calculate_restock_recommendation(10, 5, "正常"), 0)
        self.assertEqual(calculate_restock_recommendation(50, 5, "积压"), 0)

    def test_enrich_records_does_not_mutate_input(self) -> None:
        enriched = enrich_records(self.sample_records)
        self.assertNotIn("status_stok", self.sample_records[0])
        self.assertEqual(enriched[0]["status_stok"], "缺货")
        self.assertEqual(enriched[0]["nilai_stok"], 0.0)
        self.assertEqual(enriched[0]["rekomendasi_restock"], 10)
        self.assertEqual(enriched[1]["status_stok"], "预警")
        self.assertEqual(enriched[1]["nilai_stok"], 3000000.0)
        self.assertEqual(enriched[2]["status_stok"], "积压")

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
        self.assertEqual(len(search_records(enriched, "科技公司")), 2)
        self.assertEqual(search_records(enriched, "不存在的商品"), [])
        with self.assertRaises(InvalidUserInputError):
            search_records(enriched, "   ")

    def test_filter_records_single_multi_and_validation(self) -> None:
        enriched = enrich_records(self.sample_records)
        self.assertEqual(len(filter_records(enriched, status="预警")), 1)
        self.assertEqual(len(filter_records(enriched, status="KRITIS")), 1)
        self.assertEqual(
            len(
                filter_records(
                    enriched,
                    kategori="电子设备",
                    lokasi="b号仓",
                    min_harga=900000,
                    max_harga=1500000,
                )
            ),
            1,
        )
        with self.assertRaises(InvalidUserInputError):
            filter_records(enriched, status="已损坏")
        with self.assertRaises(InvalidUserInputError):
            filter_records(enriched, min_harga=-10)
        with self.assertRaises(InvalidUserInputError):
            filter_records(enriched, min_harga=50000, max_harga=10000)

    def test_group_extract_unique_and_recap(self) -> None:
        enriched = enrich_records(self.sample_records)
        grouped = group_records(enriched, "kategori")
        self.assertEqual(list(grouped.keys()), ["包装耗材", "电子设备"])
        recap = calculate_group_recap(grouped)
        self.assertEqual(recap["电子设备"]["sku_count"], 2)
        self.assertEqual(recap["电子设备"]["critical_or_out_count"], 2)
        meta = extract_unique_metadata(enriched)
        self.assertEqual(meta["kategori"], {"包装耗材", "电子设备"})
        self.assertEqual(meta["lokasi_gudang"], {"A号仓", "B号仓"})

        with self.assertRaises(InvalidUserInputError):
            group_records(enriched, "harga_satuan")

        empty_recap = calculate_group_recap({"空组": []})
        self.assertEqual(empty_recap["空组"]["average_price"], 0.0)

    def test_calculate_summary_normal_and_empty_edge_case(self) -> None:
        enriched = enrich_records(self.sample_records)
        summary = calculate_summary(enriched)
        self.assertEqual(summary["总体摘要"]["唯一SKU总数"], 3)
        self.assertEqual(summary["总体摘要"]["库存总估值IDR"], 4000000.0)
        self.assertEqual(summary["状态分布"]["缺货"], 1)
        self.assertEqual(summary["状态分布"]["预警"], 1)
        self.assertEqual(len(summary["需补货清单"]), 2)

        empty_summary = calculate_summary([])
        self.assertEqual(empty_summary["总体摘要"]["唯一SKU总数"], 0)
        self.assertEqual(empty_summary["总体摘要"]["平均单价IDR"], 0.0)
        self.assertIsNone(empty_summary["总体摘要"]["最高估值商品"])
        self.assertEqual(
            empty_summary["状态分布"],
            {"缺货": 0, "预警": 0, "正常": 0, "积压": 0},
        )
        self.assertIn("唯一 SKU 总数   : 0", format_summary_text(empty_summary))


class TestIOHandlerAndDatasetsZh(unittest.TestCase):
    """CSV/JSON 文件读写与中文数据集集成测试。"""

    def test_load_normal_dataset_end_to_end(self) -> None:
        loaded = load_inventory(DATA_INPUT_DIR / "inventory_normal.csv")
        self.assertEqual(loaded["total_raw_rows"], 28)
        self.assertEqual(loaded["rejected_rows"], [])
        deduped, dups = deduplicate_records(loaded["records"], strategy="latest")
        self.assertEqual(len(deduped), 25)
        self.assertEqual(len(dups), 3)
        enriched = enrich_records(deduped)
        summary = calculate_summary(enriched, duplicates_removed=dups)
        self.assertEqual(summary["状态分布"]["缺货"], 3)
        self.assertEqual(summary["状态分布"]["预警"], 6)
        self.assertEqual(summary["状态分布"]["正常"], 12)
        self.assertEqual(summary["状态分布"]["积压"], 4)

    def test_load_edge_empty_csv(self) -> None:
        loaded = load_inventory(DATA_INPUT_DIR / "inventory_edge_empty.csv")
        self.assertEqual(loaded["total_raw_rows"], 0)
        self.assertEqual(loaded["records"], [])
        self.assertEqual(loaded["rejected_rows"], [])

    def test_load_edge_dirty_bom_csv_non_strict_and_strict(self) -> None:
        dirty_path = DATA_INPUT_DIR / "inventory_edge_dirty.csv"
        loaded = load_inventory(dirty_path, strict=False)
        self.assertEqual(loaded["total_raw_rows"], 8)
        self.assertEqual(len(loaded["records"]), 3)
        self.assertEqual(len(loaded["rejected_rows"]), 5)
        self.assertEqual(loaded["records"][0]["sku"], "SKU-901")

        enriched = enrich_records(loaded["records"])
        self.assertEqual(enriched[0]["status_stok"], "缺货")
        self.assertEqual(enriched[1]["status_stok"], "正常")
        self.assertEqual(enriched[2]["status_stok"], "预警")

        with self.assertRaises(InvalidDataFormatError):
            load_inventory(dirty_path, strict=True)

    def test_load_edge_unicode_json(self) -> None:
        loaded = load_inventory(DATA_INPUT_DIR / "inventory_edge_unicode.json")
        self.assertEqual(loaded["format"], "json")
        self.assertEqual(loaded["total_raw_rows"], 4)
        self.assertEqual(loaded["rejected_rows"], [])
        deduped, dups = deduplicate_records(loaded["records"], strategy="latest")
        self.assertEqual(len(deduped), 3)
        self.assertEqual(len(dups), 1)
        self.assertEqual(deduped[0]["stok"], 8)
        self.assertIn("快充适配器", deduped[0]["nama_barang"])

    def test_error_conditions_for_files_and_formats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with self.assertRaises(DataFileNotFoundError):
                load_inventory(tmp / "missing.csv")
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
                json.dumps({"items": ["not_an_object"]}),
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

            save_report_json({"状态": "正常", "数量": 3}, json_out)
            parsed = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertEqual(parsed, {"状态": "正常", "数量": 3})


class TestCLIAndDebuggingRegressionsZh(unittest.TestCase):
    """CLI 端到端集成测试与中文排版/异常回归测试。"""

    def test_cli_subcommands_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out_csv = tmp / "clean.csv"
            out_json = tmp / "summary.json"
            out_filter = tmp / "critical.csv"
            out_dedup = tmp / "dedup.csv"

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        "analyze",
                        "--input",
                        str(DATA_INPUT_DIR / "inventory_normal.csv"),
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
                            str(DATA_INPUT_DIR / "inventory_normal.csv"),
                            "--query",
                            "扫描器",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "filter",
                            "--input",
                            str(DATA_INPUT_DIR / "inventory_normal.csv"),
                            "--status",
                            "预警",
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
                            str(DATA_INPUT_DIR / "inventory_normal.csv"),
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
                            str(DATA_INPUT_DIR / "inventory_normal.csv"),
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
            rc = main(["analyze", "--input", "/tmp/zh_file_does_not_exist_98765.csv"])
        self.assertEqual(rc, 1)
        self.assertIn("[错误]", err.getvalue())

        err2 = io.StringIO()
        with redirect_stderr(err2):
            rc2 = main(
                [
                    "filter",
                    "--input",
                    str(DATA_INPUT_DIR / "inventory_normal.csv"),
                    "--min-harga",
                    "500000",
                    "--max-harga",
                    "10000",
                ]
            )
        self.assertEqual(rc2, 1)
        self.assertIn("价格区间无效", err2.getvalue())

    def test_interactive_session_with_defensive_handling(self) -> None:
        answers = iter(
            [
                "9",
                "2",
                "1",
                str(DATA_INPUT_DIR / "inventory_normal.csv"),
                "latest",
                "3",
                "SKU-001",
                "4",
                "",
                "",
                "缺货",
                "不是数字",
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
        self.assertIn("未识别选项", joined)
        self.assertIn("请先通过菜单 1 加载", joined)
        self.assertIn("成功加载 25 个唯一 SKU", joined)
        self.assertIn("不是有效数字", joined)
        self.assertIn("有限的非负数", joined)
        self.assertIn("无线二维条码扫描器", joined)

    def test_csv_extra_columns_isolated_in_rejected_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "extra_cols.csv"
            csv_path.write_text(
                "sku,nama_barang,kategori,lokasi_gudang,stok,stok_minimum,harga_satuan,pemasok,tanggal_update\n"
                "SKU-1,鼠标,电子设备,A号仓,5,2,50000,供应商A,2026-11-01,多余列\n",
                encoding="utf-8",
            )
            res = load_inventory(csv_path, strict=False)
            self.assertEqual(len(res["records"]), 0)
            self.assertEqual(len(res["rejected_rows"]), 1)
            self.assertIn("超出 CSV 表头定义", res["rejected_rows"][0]["reason"])

    def test_formatter_currency_and_cjk_table(self) -> None:
        self.assertEqual(format_currency_idr(1250000), "Rp1.250.000")
        self.assertEqual(format_currency_idr(12500000.5), "Rp12.500.000,50")
        self.assertEqual(format_currency_idr(0), "Rp0")
        table = format_records_table(
            enrich_records(
                [
                    {
                        "sku": "SKU-1",
                        "nama_barang": "测试设备",
                        "kategori": "电子设备",
                        "lokasi_gudang": "A号仓",
                        "stok": 0,
                        "stok_minimum": 5,
                        "harga_satuan": 10000.0,
                        "pemasok": "测试供应商",
                        "tanggal_update": "2026-11-01",
                    }
                ]
            )
        )
        self.assertIn("商品名称", table)
        self.assertIn("缺货", table)

    def test_regression_scenario_1_empty_dataset_and_reversed_sku_dedup(self) -> None:
        """回归测试：空数据集与逆序日期重复 SKU 去重。"""
        empty_summary = calculate_summary([])
        self.assertEqual(empty_summary["总体摘要"]["唯一SKU总数"], 0)
        self.assertEqual(empty_summary["总体摘要"]["平均单价IDR"], 0.0)

        loaded = load_inventory(DATA_INPUT_DIR / "inventory_normal.csv")
        deduped, _ = deduplicate_records(loaded["records"], strategy="latest")
        sku_map = build_sku_index(deduped)
        self.assertEqual(sku_map["SKU-011"]["tanggal_update"], "2026-11-12")
        self.assertEqual(sku_map["SKU-011"]["stok"], 18)
        self.assertEqual(sku_map["SKU-019"]["tanggal_update"], "2026-11-18")
        self.assertEqual(sku_map["SKU-019"]["stok"], 24)

    def test_regression_scenario_2_utf8_bom_and_row_isolation(self) -> None:
        """回归测试：UTF-8 BOM CSV 与错误行隔离日志。"""
        loaded = load_inventory(DATA_INPUT_DIR / "inventory_edge_dirty.csv", strict=False)
        self.assertEqual(len(loaded["records"]), 3)
        self.assertEqual(len(loaded["rejected_rows"]), 5)
        reasons = " | ".join(item["reason"] for item in loaded["rejected_rows"])
        self.assertIn("sku", reasons.lower())
        self.assertIn("负数", reasons)
        self.assertIn("2026-02-30", reasons)

    def test_package_metadata_and_version_flag(self) -> None:
        self.assertEqual(inventrack_zh.__author__, "Robani Ichsan")
        self.assertEqual(inventrack_zh.__license__, "MIT")
        self.assertEqual(inventrack_zh.__version__, "1.1.0")

        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("1.1.0", out.getvalue())
        self.assertIn("Robani Ichsan", out.getvalue())

    def test_record_validation_error_tracks_offending_field(self) -> None:
        bad_row = {
            "sku": "SKU-777",
            "nama_barang": "光电传感器",
            "kategori": "电子设备",
            "lokasi_gudang": "A号仓",
            "stok": "-3",
            "stok_minimum": "2",
            "harga_satuan": "50000",
            "pemasok": "精密科技",
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
