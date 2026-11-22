"""终端文本、货币与对齐表格格式化模块（支持中文等宽对齐）。"""

from __future__ import annotations

import unicodedata
from typing import Any


def format_currency_idr(amount: float) -> str:
    """将金额格式化为印尼盾（IDR）货币字符串。

    Args:
        amount: 浮点或整数金额。

    Returns:
        例如 'Rp1.250.000' 或 'Rp1.250.000,50' 的格式化字符串。
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
    """计算字符串在等宽终端中的显示宽度（全角/中文字符计为 2）。"""
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return width


def _pad_left(text: str, width: int) -> str:
    """按终端视觉宽度左对齐填充空格。"""
    return text + (" " * max(0, width - _display_width(text)))


def _pad_right(text: str, width: int) -> str:
    """按终端视觉宽度右对齐填充空格。"""
    return (" " * max(0, width - _display_width(text))) + text


def _truncate_text(text: str, max_width: int) -> str:
    """按终端视觉宽度截断超出列宽限制的文本并追加省略号。"""
    if _display_width(text) <= max_width:
        return text
    if max_width <= 3:
        result: list[str] = []
        used = 0
        for ch in text:
            ch_w = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
            if used + ch_w > max_width:
                break
            result.append(ch)
            used += ch_w
        return "".join(result)

    limit = max_width - 3
    result = []
    used = 0
    for ch in text:
        ch_w = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if used + ch_w > limit:
            break
        result.append(ch)
        used += ch_w
    return "".join(result) + "..."


def format_records_table(records: list[dict[str, Any]], max_rows: int | None = None) -> str:
    """将库存记录列表渲染为列宽自适应的对齐 ASCII 表格。

    Args:
        records: 待展示的库存记录列表。
        max_rows: 最大展示行数限制（可选）。

    Returns:
        格式化表格字符串；当列表为空时返回友好提示。
    """
    if not records:
        return "（没有匹配的库存记录可显示。）"

    display_records = records[:max_rows] if max_rows is not None and max_rows >= 0 else records

    headers = ["SKU", "商品名称", "类别", "仓库", "库存", "安全库存", "状态", "库存估值", "建议补货"]
    rows: list[list[str]] = []
    for item in display_records:
        rows.append(
            [
                str(item.get("sku", "-")),
                _truncate_text(str(item.get("nama_barang", "-")), 32),
                _truncate_text(str(item.get("kategori", "-")), 16),
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
        cells = [
            _pad_right(value, widths[idx]) if idx in right_aligned else _pad_left(value, widths[idx])
            for idx, value in enumerate(values)
        ]
        return " | ".join(cells)

    separator = "-+-".join("-" * width for width in widths)
    lines = [_format_row(headers), separator]
    lines.extend(_format_row(row) for row in rows)
    if max_rows is not None and len(records) > len(display_records):
        lines.append(f"...（其余 {len(records) - len(display_records)} 条记录未显示）")
    return "\n".join(lines)


def format_group_recap_table(recap: dict[str, dict[str, Any]], group_label: str = "分组") -> str:
    """渲染按维度分组的统计汇总表。

    Args:
        recap: calculate_group_recap 生成的统计字典。
        group_label: 第一列表头名称（如 '类别' 或 '仓库'）。

    Returns:
        对齐后的分组汇总表字符串。
    """
    if not recap:
        return f"（暂无 {group_label} 分组汇总数据。）"

    headers = [group_label, "SKU数", "总件数", "总估值", "平均单价", "缺货/预警数"]
    rows: list[list[str]] = []
    for key, stats in recap.items():
        rows.append(
            [
                key,
                str(stats["sku_count"]),
                str(stats["total_units"]),
                format_currency_idr(stats["total_valuation"]),
                format_currency_idr(stats["average_price"]),
                str(stats["critical_or_out_count"]),
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


def format_rejected_rows(rejected_rows: list[dict[str, Any]]) -> str:
    """格式化校验阶段被隔离拒绝的异常行清单。"""
    if not rejected_rows:
        return "没有被拒绝的无效记录。"
    lines = [f"已拒绝无效记录（{len(rejected_rows)} 条）："]
    for entry in rejected_rows:
        lines.append(
            f"  - [第 {entry.get('row_number', '?')} 行 | SKU: {entry.get('sku', '-')}] "
            f"{entry.get('reason', '未知原因')}"
        )
    return "\n".join(lines)


def format_duplicates_log(duplicates: list[dict[str, Any]]) -> str:
    """格式化 SKU 去重审计日志。"""
    if not duplicates:
        return "未发现重复 SKU。"
    lines = [f"已处理重复 SKU（{len(duplicates)} 条）："]
    for entry in duplicates:
        lines.append(
            f"  - [{entry.get('sku', '-')}] {entry.get('reason', '')}"
        )
    return "\n".join(lines)


def format_summary_text(summary: dict[str, Any]) -> str:
    """渲染完整的仓库库存分析终端摘要报告。

    Args:
        summary: calculate_summary 生成的分析摘要字典。

    Returns:
        结构化多段式终端报告字符串。
    """
    umum = summary["总体摘要"]
    dist = summary["状态分布"]
    meta = summary["唯一元数据"]
    restock = summary["需补货清单"]

    lines: list[str] = [
        "======================================================================",
        "                       仓库库存数据分析摘要报告                       ",
        "======================================================================",
        f"唯一 SKU 总数   : {umum['唯一SKU总数']}",
        f"库存总件数      : {umum['库存总件数']}",
        f"库存总估值      : {format_currency_idr(umum['库存总估值IDR'])}",
        f"平均单价        : {format_currency_idr(umum['平均单价IDR'])}",
        f"已处理重复 SKU  : {umum['已处理重复数']}",
        f"已拒绝无效行    : {umum['已拒绝行数']}",
    ]

    if umum["最高估值商品"] is not None:
        top = umum["最高估值商品"]
        low = umum["最低估值商品"]
        lines.append(
            f"最高估值商品    : {top['sku']} - {top['nama_barang']} "
            f"({format_currency_idr(top['nilai_stok'])})"
        )
        lines.append(
            f"最低估值商品    : {low['sku']} - {low['nama_barang']} "
            f"({format_currency_idr(low['nilai_stok'])})"
        )

    lines.extend(
        [
            "",
            "[库存状态分布]",
            f"  缺货 : {dist['缺货']}",
            f"  预警 : {dist['预警']}",
            f"  正常 : {dist['正常']}",
            f"  积压 : {dist['积压']}",
            "",
            "[唯一元数据]",
            f"  类别 ({len(meta['kategori'])}) : {', '.join(meta['kategori']) or '-'}",
            f"  仓库 ({len(meta['lokasi_gudang'])}) : {', '.join(meta['lokasi_gudang']) or '-'}",
            f"  供应商 ({len(meta['pemasok'])}) : {', '.join(meta['pemasok']) or '-'}",
            "",
            "[按类别汇总]",
            format_group_recap_table(summary["按类别汇总"], "类别"),
            "",
            "[按仓库汇总]",
            format_group_recap_table(summary["按仓库汇总"], "仓库"),
            "",
            f"[需补货商品清单（{len(restock)} 个 SKU）]",
        ]
    )

    if not restock:
        lines.append("  所有商品库存均处于正常或积压水平。")
    else:
        for item in restock:
            lines.append(
                f"  - [{item['status_stok']}] {item['sku']} | {item['nama_barang']} "
                f"({item['lokasi_gudang']}) -> 库存: {item['stok']}/{item['stok_minimum']}, "
                f"建议补货: +{item['rekomendasi_restock']} 件"
            )

    if summary["去重日志"]:
        lines.extend(["", format_duplicates_log(summary["去重日志"])])
    if summary["拒绝行日志"]:
        lines.extend(["", format_rejected_rows(summary["拒绝行日志"])])

    lines.append("======================================================================")
    return "\n".join(lines)
