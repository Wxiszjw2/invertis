<div align="center">

# InvenTrack CLI（简体中文独立版）

**纯 Python 标准库编写的简体中文仓库库存分析工具（源码、界面与示例数据全中文化）**

[返回主文档 (Bahasa Indonesia)](../README.md) | [简体中文说明](../README.zh-CN.md)

</div>

---

本目录 `zh/` 为 **InvenTrack CLI** 的独立简体中文代码版本，内部保留与主程序相同的模块化架构与防御式校验逻辑，同时将以下内容全面中文化：

- 全部模块文档字符串（docstrings）、行内注释与自定义异常提示
- 命令行 `--help`、交互式菜单、库存状态标签（`缺货` / `预警` / `正常` / `积压`）与错误/去重审计日志
- 终端表格输出（内置基于 `unicodedata.east_asian_width` 的中文等宽对齐排版）
- 示例输入/输出数据集（[`data/input/`](data/input) 与 [`data/output/`](data/output)）及 30 项独立单元测试（[`tests/test_inventrack_zh.py`](tests/test_inventrack_zh.py)）

## 快速运行

```bash
# 从仓库根目录运行
python3 zh/main.py

# 或进入 zh/ 目录运行
cd zh
python3 main.py
# 或以模块方式运行
python3 -m inventrack_zh
```

### 常用 CLI 子命令

```bash
# 完整分析并导出规范化 CSV 与 JSON 报告
python3 zh/main.py analyze \
  --output-csv zh/data/output/inventory_clean.csv \
  --output-json zh/data/output/analysis_report.json

# 关键词检索
python3 zh/main.py search --query "扫描器"

# 筛选“预警”商品并导出 CSV
python3 zh/main.py filter --status 预警 --output-csv zh/data/output/filter_critical.csv

# 按仓库汇总统计
python3 zh/main.py group --by lokasi_gudang
```

## 运行中文版测试

```bash
# 从仓库根目录执行
python3 -m unittest discover -s zh/tests -v

# 或在 zh/ 目录内执行
python3 -m unittest discover -s tests -v
```

---

由 **Robani Ichsan**（[GitHub @Wxiszjw2](https://github.com/Wxiszjw2) · [Gitee @Wxiszjw](https://gitee.com/Wxiszjw)）设计与开发 · [MIT License](../LICENSE)
