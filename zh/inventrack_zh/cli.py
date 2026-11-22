"""InvenTrack CLI（简体中文版）命令行子命令与交互式会话入口模块。"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from inventrack_zh.exceptions import InvalidUserInputError, InvenTrackError
from inventrack_zh.formatter import (
    format_duplicates_log,
    format_group_recap_table,
    format_records_table,
    format_rejected_rows,
    format_summary_text,
)
from inventrack_zh.io_handler import load_inventory, save_inventory_csv, save_report_json
from inventrack_zh.processor import (
    calculate_group_recap,
    calculate_summary,
    deduplicate_records,
    enrich_records,
    filter_records,
    group_records,
    search_records,
)
from inventrack_zh.validators import VALID_DEDUP_STRATEGIES, VALID_GROUP_FIELDS

APP_NAME: Final[str] = "InvenTrack CLI"
APP_VERSION: Final[str] = "1.1.0"
APP_AUTHOR: Final[str] = "Robani Ichsan"
DEFAULT_INPUT_FILE: Final[str] = "data/input/inventory_normal.csv"

EXIT_OK: Final[int] = 0
EXIT_DOMAIN_ERROR: Final[int] = 1
EXIT_INTERRUPTED: Final[int] = 130

GROUP_DISPLAY_LABELS: Final[dict[str, str]] = {
    "kategori": "类别",
    "lokasi_gudang": "仓库",
    "status_stok": "库存状态",
    "pemasok": "供应商",
}


def _resolve_default_input() -> str | None:
    """若工作目录或 zh 根目录下存在默认数据集，则返回其相对或绝对路径。"""
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


def _resolve_cli_input(raw_input: str | None) -> str:
    """解析命令行 --input 参数；未显式传入时使用中文版默认演示文件。"""
    if raw_input is not None:
        return raw_input
    resolved = _resolve_default_input()
    return resolved if resolved is not None else DEFAULT_INPUT_FILE


def _load_and_prepare(
    input_path: str,
    *,
    dedup_strategy: str = "latest",
    strict: bool = False,
) -> dict[str, Any]:
    """加载文件、执行去重、计算衍生字段并汇总分析结果。"""
    loaded = load_inventory(input_path, strict=strict)
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
    """执行 analyze 子命令：加载、去重、分析、打印摘要并按需导出。"""
    prepared = _load_and_prepare(
        _resolve_cli_input(args.input),
        dedup_strategy=args.dedup_strategy,
        strict=args.strict,
    )
    print(f"数据源   : {prepared['source_file']}（{prepared['format'].upper()} 格式）")
    print(f"原始行数 : {prepared['total_raw_rows']}")
    print(format_summary_text(prepared["summary"]))

    if args.output_csv:
        saved_csv = save_inventory_csv(prepared["records"], args.output_csv)
        print(f"已导出规范化 CSV : {saved_csv}")
    if args.output_json:
        report_payload = {
            "源文件": prepared["source_file"],
            "源格式": prepared["format"],
            "原始记录总数": prepared["total_raw_rows"],
            "去重策略": args.dedup_strategy,
            **prepared["summary"],
        }
        saved_json = save_report_json(report_payload, args.output_json)
        print(f"已导出分析 JSON  : {saved_json}")
    return EXIT_OK


def _handle_search(args: argparse.Namespace) -> int:
    """执行 search 子命令：按 SKU 或关键词搜索记录。"""
    prepared = _load_and_prepare(
        _resolve_cli_input(args.input),
        dedup_strategy=args.dedup_strategy,
    )
    matches = search_records(prepared["records"], args.query)
    print(f"搜索 '{args.query}' 的结果（共找到 {len(matches)} 条）：")
    print(format_records_table(matches))
    return EXIT_OK


def _handle_filter(args: argparse.Namespace) -> int:
    """执行 filter 子命令：按多条件筛选并支持导出 CSV。"""
    prepared = _load_and_prepare(
        _resolve_cli_input(args.input),
        dedup_strategy=args.dedup_strategy,
    )
    filtered = filter_records(
        prepared["records"],
        kategori=args.kategori,
        lokasi=args.lokasi,
        status=args.status,
        min_harga=args.min_harga,
        max_harga=args.max_harga,
    )
    print(f"筛选结果（{len(filtered)} / {len(prepared['records'])} 个 SKU）：")
    print(format_records_table(filtered))
    if args.output_csv:
        saved_csv = save_inventory_csv(filtered, args.output_csv)
        print(f"筛选结果已导出至 CSV : {saved_csv}")
    return EXIT_OK


def _handle_group(args: argparse.Namespace) -> int:
    """执行 group 子命令并显示按维度汇总的统计表。"""
    prepared = _load_and_prepare(
        _resolve_cli_input(args.input),
        dedup_strategy=args.dedup_strategy,
    )
    grouped = group_records(prepared["records"], group_by=args.by)
    recap = calculate_group_recap(grouped)
    label = GROUP_DISPLAY_LABELS.get(args.by, args.by)
    print(f"按 '{label}'（{args.by}）分组汇总结果：")
    print(format_group_recap_table(recap, label))
    return EXIT_OK


def _handle_deduplicate(args: argparse.Namespace) -> int:
    """执行 deduplicate 子命令并保存去重后的 CSV 文件。"""
    prepared = _load_and_prepare(
        _resolve_cli_input(args.input),
        dedup_strategy=args.strategy,
    )
    saved_csv = save_inventory_csv(prepared["records"], args.output_csv)
    print(
        f"去重完成（策略='{args.strategy}'）："
        f"共 {len(prepared['records'])} 个唯一 SKU 已保存至 {saved_csv}。"
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
    """防御式读取可选的非负有限浮点数（直接回车表示跳过）。"""
    while True:
        raw = input_fn(prompt_text).strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            output_fn(f"输入 '{raw}' 不是有效数字，请输入数字或直接按回车跳过。")
            continue
        if not math.isfinite(value) or value < 0:
            output_fn("数值必须为有限的非负数，请重新输入。")
            continue
        return value


def run_interactive_session(
    initial_input: str | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> int:
    """运行终端交互式菜单会话直至用户退出。"""
    state: dict[str, Any] | None = None
    output_fn(f"=== {APP_NAME} v{APP_VERSION} · 作者: {APP_AUTHOR} — 交互式库存分析模式 ===")

    if initial_input:
        try:
            state = _load_and_prepare(initial_input)
            output_fn(f"已成功加载 '{state['source_file']}'（{len(state['records'])} 个唯一 SKU）。")
        except InvenTrackError as exc:
            output_fn(f"[警告] 默认文件加载失败：{exc}")

    while True:
        active_file = state["source_file"] if state else "（尚未加载文件）"
        output_fn(f"\n当前文件: {active_file}")
        output_fn("功能菜单:")
        output_fn("  1. 加载库存数据文件 (CSV/JSON)")
        output_fn("  2. 查看数据分析摘要")
        output_fn("  3. 搜索商品 (SKU / 关键词)")
        output_fn("  4. 多条件筛选商品")
        output_fn("  5. 分组汇总统计")
        output_fn("  6. 导出规范化 CSV 与 JSON 报告")
        output_fn("  0. 退出")

        try:
            choice = input_fn("请选择菜单编号 [0-6]: ").strip()
        except (EOFError, KeyboardInterrupt):
            output_fn("\n交互式会话已中断。")
            return EXIT_OK

        if choice == "0":
            output_fn(f"感谢使用 {APP_NAME}，再见。")
            return EXIT_OK

        if choice not in {"1", "2", "3", "4", "5", "6"}:
            output_fn(f"未识别选项 '{choice}'，请输入 0 到 6 之间的数字。")
            continue

        if choice == "1":
            path_input = input_fn("请输入文件路径 (.csv/.json): ").strip()
            if not path_input:
                path_input = _resolve_default_input() or DEFAULT_INPUT_FILE
            strategy = input_fn("去重策略 [latest/first] (默认: latest): ").strip() or "latest"
            try:
                state = _load_and_prepare(path_input, dedup_strategy=strategy)
                output_fn(
                    f"成功加载 {len(state['records'])} 个唯一 SKU"
                    f"（处理重复：{len(state['duplicates'])}，"
                    f"拒绝行：{len(state['rejected_rows'])}）。"
                )
            except InvenTrackError as exc:
                output_fn(f"[错误] {exc}")
            continue

        if state is None:
            output_fn("[警告] 请先通过菜单 1 加载库存数据文件。")
            continue

        if choice == "2":
            output_fn(format_summary_text(state["summary"]))
        elif choice == "3":
            query = input_fn("请输入 SKU 或搜索关键词: ")
            try:
                matches = search_records(state["records"], query)
                output_fn(f"共找到 {len(matches)} 条商品记录：")
                output_fn(format_records_table(matches))
            except InvalidUserInputError as exc:
                output_fn(f"[错误] {exc}")
        elif choice == "4":
            kategori = input_fn("筛选类别（留空表示全部）: ").strip() or None
            lokasi = input_fn("筛选仓库（留空表示全部）: ").strip() or None
            status = input_fn("筛选状态 [缺货/预警/正常/积压]（留空表示全部）: ").strip() or None
            min_harga = prompt_optional_float(
                "最低单价（留空表示不限）: ",
                input_fn=input_fn,
                output_fn=output_fn,
            )
            max_harga = prompt_optional_float(
                "最高单价（留空表示不限）: ",
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
                output_fn(f"筛选结果（共 {len(filtered)} 条商品）：")
                output_fn(format_records_table(filtered))
            except InvalidUserInputError as exc:
                output_fn(f"[错误] {exc}")
        elif choice == "5":
            group_by = (
                input_fn("分组字段 [kategori/lokasi_gudang/status_stok/pemasok] (默认: kategori): ").strip()
                or "kategori"
            )
            try:
                grouped = group_records(state["records"], group_by=group_by)
                recap = calculate_group_recap(grouped)
                output_fn(format_group_recap_table(recap, GROUP_DISPLAY_LABELS.get(group_by, group_by)))
            except InvalidUserInputError as exc:
                output_fn(f"[错误] {exc}")
        elif choice == "6":
            csv_out = input_fn("导出规范化 CSV 路径（留空跳过）: ").strip()
            json_out = input_fn("导出分析 JSON 路径（留空跳过）: ").strip()
            try:
                if csv_out:
                    saved_csv = save_inventory_csv(state["records"], csv_out)
                    output_fn(f"CSV 已保存至: {saved_csv}")
                if json_out:
                    payload = {
                        "源文件": state["source_file"],
                        "源格式": state["format"],
                        "原始记录总数": state["total_raw_rows"],
                        **state["summary"],
                    }
                    saved_json = save_report_json(payload, json_out)
                    output_fn(f"JSON 已保存至: {saved_json}")
                if not csv_out and not json_out:
                    output_fn("未指定任何导出文件。")
            except InvenTrackError as exc:
                output_fn(f"[错误] {exc}")


def build_parser() -> argparse.ArgumentParser:
    """构建主命令行参数解析器及全部子命令。"""
    parser = argparse.ArgumentParser(
        prog="inventrack-zh",
        description=f"{APP_NAME}（简体中文版）— 确定性多仓库库存数据校验、去重与补货分析命令行工具。",
        epilog=f"作者: {APP_AUTHOR} · 零第三方依赖（基于 Python 标准库构建）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"{APP_NAME} {APP_VERSION} (作者: {APP_AUTHOR})",
        help="显示程序版本号与作者信息。",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用子命令列表")

    p_analyze = subparsers.add_parser("analyze", help="加载、校验、去重并生成完整分析摘要。")
    p_analyze.add_argument(
        "--input",
        default=None,
        help=f"输入文件路径（.csv 或 .json，默认: {DEFAULT_INPUT_FILE}）。",
    )
    p_analyze.add_argument("--output-csv", help="规范化 CSV 输出路径（可选）。")
    p_analyze.add_argument("--output-json", help="分析报告 JSON 输出路径（可选）。")
    p_analyze.add_argument(
        "--dedup-strategy",
        default="latest",
        choices=sorted(VALID_DEDUP_STRATEGIES),
        help="重复 SKU 处理策略（默认: latest）。",
    )
    p_analyze.add_argument(
        "--strict",
        action="store_true",
        help="启用严格模式：只要发现任意无效行立即报错中止。",
    )

    p_search = subparsers.add_parser("search", help="按 SKU 或关键词跨字段检索商品。")
    p_search.add_argument(
        "--input",
        default=None,
        help=f"输入文件路径（.csv 或 .json，默认: {DEFAULT_INPUT_FILE}）。",
    )
    p_search.add_argument("--query", required=True, help="搜索关键词（SKU、名称、类别、供应商或仓库）。")
    p_search.add_argument(
        "--dedup-strategy",
        default="latest",
        choices=sorted(VALID_DEDUP_STRATEGIES),
        help="重复 SKU 处理策略（默认: latest）。",
    )

    p_filter = subparsers.add_parser("filter", help="按类别、仓库、状态与价格区间多条件筛选商品。")
    p_filter.add_argument(
        "--input",
        default=None,
        help=f"输入文件路径（.csv 或 .json，默认: {DEFAULT_INPUT_FILE}）。",
    )
    p_filter.add_argument("--kategori", help="按类别筛选。")
    p_filter.add_argument("--lokasi", help="按仓库编码/名称筛选。")
    p_filter.add_argument(
        "--status",
        choices=["缺货", "预警", "正常", "积压", "HABIS", "KRITIS", "AMAN", "BERLEBIH"],
        help="按库存状态筛选（缺货/预警/正常/积压）。",
    )
    p_filter.add_argument("--min-harga", type=float, help="最低单价限制。")
    p_filter.add_argument("--max-harga", type=float, help="最高单价限制。")
    p_filter.add_argument("--output-csv", help="将筛选结果导出至 CSV（可选）。")
    p_filter.add_argument(
        "--dedup-strategy",
        default="latest",
        choices=sorted(VALID_DEDUP_STRATEGIES),
        help="重复 SKU 处理策略（默认: latest）。",
    )

    p_group = subparsers.add_parser("group", help="按指定维度分组并显示统计汇总。")
    p_group.add_argument(
        "--input",
        default=None,
        help=f"输入文件路径（.csv 或 .json，默认: {DEFAULT_INPUT_FILE}）。",
    )
    p_group.add_argument(
        "--by",
        default="kategori",
        choices=sorted(VALID_GROUP_FIELDS),
        help="分组维度字段（默认: kategori）。",
    )
    p_group.add_argument(
        "--dedup-strategy",
        default="latest",
        choices=sorted(VALID_DEDUP_STRATEGIES),
        help="重复 SKU 处理策略（默认: latest）。",
    )

    p_dedup = subparsers.add_parser("deduplicate", help="清理重复 SKU 并导出至新 CSV。")
    p_dedup.add_argument(
        "--input",
        default=None,
        help=f"输入文件路径（.csv 或 .json，默认: {DEFAULT_INPUT_FILE}）。",
    )
    p_dedup.add_argument("--output-csv", required=True, help="去重后的 CSV 输出路径。")
    p_dedup.add_argument(
        "--strategy",
        default="latest",
        choices=sorted(VALID_DEDUP_STRATEGIES),
        help="去重策略（默认: latest）。",
    )

    p_inter = subparsers.add_parser("interactive", help="启动终端交互式菜单模式。")
    p_inter.add_argument("--input", help="启动时自动加载的初始数据文件（可选）。")

    return parser


def main(argv: list[str] | None = None) -> int:
    """InvenTrack CLI（简体中文版）主函数。"""
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
        print(f"[错误] {exc}", file=sys.stderr)
        return EXIT_DOMAIN_ERROR
    except KeyboardInterrupt:
        print("\n操作已被用户取消。", file=sys.stderr)
        return EXIT_INTERRUPTED
