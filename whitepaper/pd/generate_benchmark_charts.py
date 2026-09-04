#!/usr/bin/env python3

import argparse
import re
from pathlib import Path

import xlsxwriter


BLUE = "#4472C4"
ORANGE = "#ED7D31"
GREEN = "#70AD47"
GRAY = "#7F7F7F"
LIGHT_BLUE = "#D9EAF7"
LIGHT_ORANGE = "#FCE4D6"
LIGHT_GREEN = "#E2F0D9"
RED = "#C00000"


def section(text, start, end=None):
    begin = text.index(start)
    finish = text.index(end, begin) if end else len(text)
    return text[begin:finish]


def split_row(line):
    return [cell.strip().replace("`", "") for cell in line.strip().strip("|").split("|")]


def extract_tables(text):
    lines = text.splitlines()
    tables = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("|"):
            index += 1
            continue
        block = []
        while index < len(lines) and lines[index].startswith("|"):
            block.append(lines[index])
            index += 1
        if len(block) < 3:
            continue
        headers = split_row(block[0])
        rows = [split_row(line) for line in block[2:]]
        tables.append((headers, rows))
    return tables


def pick_table(text, required_headers, occurrence=0):
    matches = []
    for headers, rows in extract_tables(text):
        if all(header in headers for header in required_headers):
            matches.append((headers, rows))
    if occurrence >= len(matches):
        raise ValueError(f"table not found: {required_headers}, occurrence={occurrence}")
    return matches[occurrence]


def number(value):
    cleaned = value.replace(",", "").replace("%", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        raise ValueError(f"numeric value not found: {value}")
    return float(match.group(0))


def integer(value):
    return int(number(value))


def assert_close(actual, expected, label, tolerance=1e-6):
    if abs(actual - expected) > tolerance:
        raise ValueError(f"{label}: expected {expected}, found {actual}")


def case_label(isl, osl, concurrency):
    def short(value):
        value = int(value)
        return f"{value // 1024}K" if value >= 1024 else str(value)

    return f"I{short(isl)}-O{short(osl)}-C{int(concurrency)}"


def write_table(ws, row, col, headers, rows, formats, widths=None):
    for offset, header in enumerate(headers):
        ws.write(row, col + offset, header, formats["header"])
    for row_offset, values in enumerate(rows, 1):
        for col_offset, value in enumerate(values):
            fmt = formats["text"] if isinstance(value, str) else formats["number"]
            ws.write(row + row_offset, col + col_offset, value, fmt)
    if widths:
        for offset, width in enumerate(widths):
            ws.set_column(col + offset, col + offset, width)
    ws.autofilter(row, col, row + len(rows), col + len(headers) - 1)
    return row + len(rows)


def configure_chart(chart, title, y_axis, legend=True, y_min=None, y_max=None):
    chart.set_title({"name": title, "name_font": {"size": 13, "bold": True}})
    chart.set_x_axis({"label_position": "low"})
    axis = {
        "name": y_axis,
        "major_gridlines": {"visible": True, "line": {"color": "#D9D9D9"}},
    }
    if y_min is not None:
        axis["min"] = y_min
    if y_max is not None:
        axis["max"] = y_max
    chart.set_y_axis(axis)
    chart.set_legend({"position": "bottom"} if legend else {"none": True})
    chart.set_chartarea({"border": {"none": True}})
    chart.set_plotarea({"border": {"color": "#D9D9D9"}})
    chart.set_size({"width": 680, "height": 360})


def add_baseline(workbook, chart, sheet, first_row, last_row, category_col, value_col, color=GRAY):
    line = workbook.add_chart({"type": "line"})
    line.add_series(
        {
            "name": "Reference",
            "categories": [sheet, first_row, category_col, last_row, category_col],
            "values": [sheet, first_row, value_col, last_row, value_col],
            "line": {"color": color, "width": 1.5, "dash_type": "dash"},
            "marker": {"type": "none"},
        }
    )
    chart.combine(line)


def ratio_chart(workbook, sheet, first_row, last_row, category_col, series, baseline_col, title, y_axis, y_min, y_max):
    chart = workbook.add_chart({"type": "column", "subtype": "clustered"})
    for name, value_col, color in series:
        chart.add_series(
            {
                "name": name,
                "categories": [sheet, first_row, category_col, last_row, category_col],
                "values": [sheet, first_row, value_col, last_row, value_col],
                "fill": {"color": color},
                "border": {"none": True},
            }
        )
    add_baseline(workbook, chart, sheet, first_row, last_row, category_col, baseline_col)
    configure_chart(chart, title, y_axis, y_min=y_min, y_max=y_max)
    return chart


def clustered_chart(workbook, sheet, first_row, last_row, category_col, series, title, y_axis):
    chart = workbook.add_chart({"type": "column", "subtype": "clustered"})
    for name, value_col, color in series:
        chart.add_series(
            {
                "name": name,
                "categories": [sheet, first_row, category_col, last_row, category_col],
                "values": [sheet, first_row, value_col, last_row, value_col],
                "fill": {"color": color},
                "border": {"none": True},
            }
        )
    configure_chart(chart, title, y_axis)
    return chart


def build_workbook(report_path, output_path):
    text = report_path.read_text(encoding="utf-8")

    raw_section = section(text, "## 6. Canonical Raw versus llm-d 1P1D", "## 7.")
    raw_summary_headers, raw_summary_rows = pick_table(raw_section, ["Metric", "Suite/geo ratio"])
    raw_group_headers, raw_group_rows = pick_table(raw_section, ["Dimension", "Group", "Throughput"])
    raw_case_headers, raw_case_rows = pick_table(raw_section, ["Raw out tok/s", "llm-d out tok/s"])

    agg_section = section(text, "## 7. Aggregate baseline", "## 8.")
    agg_summary_headers, agg_summary_rows = pick_table(agg_section, ["Metric", "Geomean Aggregate/P-D"])
    agg_case_headers, agg_case_rows = pick_table(agg_section, ["Aggregate out", "llm-d P/D out"])

    topology_section = section(text, "## 8. Equal-resource 2P2D versus 1P3D", "## 9.")
    topology_total_headers, topology_total_rows = pick_table(topology_section, ["Topology", "Suite-normalized out tok/s"])
    topology_summary_headers, topology_summary_rows = pick_table(topology_section, ["Metric", "Geomean", "Median"])
    topology_group_headers, topology_group_rows = pick_table(topology_section, ["Dimension", "Group", "Throughput"])
    topology_case_headers, topology_case_rows = pick_table(topology_section, ["2P2D out", "1P3D out"])

    failure_section = section(text, "## 9. 3P1D capacity/liveness failure", "## 10.")
    failure_headers, failure_rows = pick_table(failure_section, ["Evidence", "First attempt", "Second attempt"])

    independent = section(text, "### 10.2 Independent-workload arms", "### 10.3")
    indep_arm_headers, indep_arm_rows = pick_table(independent, ["Arm", "Topology", "Out tok/s"])
    indep_mean_headers, indep_mean_rows = pick_table(independent, ["Metric", "Aggregate mean", "2P2D mean"])

    shared = section(text, "### 10.3 Shared-prefix arms", "### 10.4")
    shared_arm_headers, shared_arm_rows = pick_table(shared, ["Arm", "Topology", "Out tok/s"])
    shared_mean_headers, shared_mean_rows = pick_table(shared, ["Metric", "Aggregate mean", "2P2D mean"])

    long_output = section(text, "### 10.4 Long-output arms", "## 11.")
    long_arm_headers, long_arm_rows = pick_table(long_output, ["Arm", "Topology", "Out tok/s"])
    long_mean_headers, long_mean_rows = pick_table(long_output, ["Metric", "Aggregate mean", "2P2D mean"])

    confirmation = section(text, "## 11. Third independent-workload pair", "## 12.")
    confirm_headers, confirm_rows = pick_table(confirmation, ["Metric", "Aggregate", "2P2D"])

    expected_counts = {
        "Raw/llm-d cases": (len(raw_case_rows), 24),
        "Aggregate/1P1D cases": (len(agg_case_rows), 10),
        "2P2D/1P3D cases": (len(topology_case_rows), 24),
        "Independent ABBA arms": (len(indep_arm_rows), 4),
        "Shared-prefix ABBA arms": (len(shared_arm_rows), 4),
        "Long-output ABBA arms": (len(long_arm_rows), 4),
    }
    for label, (actual, expected) in expected_counts.items():
        if actual != expected:
            raise ValueError(f"{label}: expected {expected}, found {actual}")

    raw_metric_check = {row[0]: number(row[1]) for row in raw_summary_rows}
    agg_metric_check = {row[0]: number(row[3]) for row in agg_summary_rows}
    topology_group_check = {(row[0], integer(row[1])): number(row[2]) for row in topology_group_rows}
    indep_metric_check = {row[0]: number(row[3]) for row in indep_mean_rows}
    assert_close(raw_metric_check["Output throughput"], 0.99472, "Raw/llm-d suite throughput")
    assert_close(agg_metric_check["p99 TTFT"], 0.6770, "Aggregate/P-D p99 TTFT")
    assert_close(agg_metric_check["p99 TPOT"], 1.9335, "Aggregate/P-D p99 TPOT")
    assert_close(topology_group_check[("OSL", 128)], 0.6600, "1P3D/2P2D OSL128 throughput")
    assert_close(topology_group_check[("OSL", 1024)], 1.0624, "1P3D/2P2D OSL1024 throughput")
    assert_close(indep_metric_check["Output throughput"], 1.5265, "Aggregate/2P2D independent throughput")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(output_path)
    workbook.set_properties(
        {
            "title": "Qwen3-32B P/D and Topology Benchmark Charts on Intel B60",
            "subject": "Chart companion to whitepaper/pd/qwen3-32b-intel-b60-benchmark.md",
            "author": "llm-d benchmark report",
            "comments": "Generated from the Markdown report by generate_benchmark_charts.py",
        }
    )

    formats = {
        "title": workbook.add_format({"bold": True, "font_size": 18, "font_color": "#1F4E78"}),
        "section": workbook.add_format({"bold": True, "font_size": 13, "font_color": "#1F4E78", "bottom": 1}),
        "header": workbook.add_format({"bold": True, "font_color": "white", "bg_color": "#1F4E78", "border": 1, "text_wrap": True, "valign": "vcenter"}),
        "text": workbook.add_format({"border": 1, "valign": "top"}),
        "number": workbook.add_format({"border": 1, "num_format": "0.000"}),
        "integer": workbook.add_format({"border": 1, "num_format": "0"}),
        "ratio": workbook.add_format({"border": 1, "num_format": '0.0000"x"'}),
        "percent": workbook.add_format({"border": 1, "num_format": "0.0%;[Red]-0.0%"}),
        "note": workbook.add_format({"font_color": "#666666", "italic": True, "text_wrap": True}),
        "link": workbook.add_format({"font_color": "blue", "underline": 1}),
        "good": workbook.add_format({"bg_color": LIGHT_GREEN, "border": 1, "num_format": "0.000"}),
        "warning": workbook.add_format({"bg_color": LIGHT_ORANGE, "border": 1, "num_format": "0.000"}),
    }

    readme = workbook.add_worksheet("00_Readme")
    readme.hide_gridlines(2)
    readme.set_column("A:A", 24)
    readme.set_column("B:B", 95)
    readme.write("A1", "Qwen3-32B P/D Benchmark Chart Workbook", formats["title"])
    readme.write("A3", "Source report", formats["section"])
    readme.write_url(
        "B3",
        "https://github.com/yao531441/llm-d/blob/xpu-whitepaper/whitepaper/pd/qwen3-32b-intel-b60-benchmark.md",
        formats["link"],
        "whitepaper/pd/qwen3-32b-intel-b60-benchmark.md",
    )
    notes = [
        ("Purpose", "Convert the first P/D/topology report tables into editable Excel charts without changing the report's comparison scope."),
        ("Throughput", "Higher is better."),
        ("TTFT / TPOT / E2E", "Lower is better."),
        ("Ratio direction", "Every sheet states its numerator and denominator. A dashed reference line marks parity."),
        ("Aggregate vs 1P1D", "Only the ten same-node cases are compared."),
        ("2P2D vs 1P3D", "Both topologies use 16 XPUs; effects remain workload-dependent."),
        ("3P1D", "Failure evidence only. It is never plotted as a performance result."),
        ("Dashboard", "Eight selected charts summarize the main comparisons; detailed sheets retain source rows and additional charts."),
        ("Regeneration", "Run: python3 whitepaper/pd/generate_benchmark_charts.py"),
        ("Dependency", "Python 3 and XlsxWriter 3.x."),
    ]
    row = 5
    for label, note in notes:
        readme.write(row, 0, label, formats["header"])
        readme.write(row, 1, note, formats["text"])
        row += 1
    readme.write(row + 1, 0, "Sheets", formats["section"])
    sheet_notes = [
        ("01_Raw_vs_llmd", "24 paired Raw/llm-d cases, suite ratios, grouped ratios, and delta charts."),
        ("02_Agg_vs_1P1D", "Ten strict same-node comparisons and TTFT/TPOT trade-off charts."),
        ("03_2P2D_vs_1P3D", "Equal-resource 24-case data, grouped ratios, and throughput heatmap."),
        ("04_Equal_ABBA", "Independent, shared-prefix, and long-output equal-resource ABBA results."),
        ("05_3P1D_Failure", "Two reproduced liveness failures, kept separate from performance charts."),
        ("06_Dashboard", "Eight publication-oriented summary charts."),
    ]
    for offset, (name, note) in enumerate(sheet_notes, row + 2):
        readme.write(offset, 0, name, formats["header"])
        readme.write(offset, 1, note, formats["text"])

    raw_ws = workbook.add_worksheet("01_Raw_vs_llmd")
    raw_ws.freeze_panes(2, 0)
    raw_ws.write("A1", "Raw vLLM P/D versus llm-d 1P1D", formats["title"])
    raw_headers = [
        "Case", "ISL", "OSL", "C", "Node", "Raw out tok/s", "llm-d out tok/s",
        "Throughput delta", "Raw p99 TTFT s", "llm-d p99 TTFT s",
        "Raw p99 TPOT ms", "llm-d p99 TPOT ms", "Parity",
    ]
    for col, header in enumerate(raw_headers):
        raw_ws.write(1, col, header, formats["header"])
    for row_index, row_values in enumerate(raw_case_rows, 2):
        isl, osl, concurrency = integer(row_values[0]), integer(row_values[1]), integer(row_values[2])
        raw_ws.write(row_index, 0, case_label(isl, osl, concurrency), formats["text"])
        raw_ws.write_number(row_index, 1, isl, formats["integer"])
        raw_ws.write_number(row_index, 2, osl, formats["integer"])
        raw_ws.write_number(row_index, 3, concurrency, formats["integer"])
        raw_ws.write(row_index, 4, row_values[3], formats["text"])
        raw_ws.write_number(row_index, 5, number(row_values[4]), formats["number"])
        raw_ws.write_number(row_index, 6, number(row_values[5]), formats["number"])
        throughput_delta = number(row_values[5]) / number(row_values[4]) - 1
        raw_ws.write_formula(
            row_index,
            7,
            f"=G{row_index + 1}/F{row_index + 1}-1",
            formats["percent"],
            throughput_delta,
        )
        raw_ws.write_number(row_index, 8, number(row_values[7]), formats["number"])
        raw_ws.write_number(row_index, 9, number(row_values[8]), formats["number"])
        raw_ws.write_number(row_index, 10, number(row_values[9]), formats["number"])
        raw_ws.write_number(row_index, 11, number(row_values[10]), formats["number"])
        raw_ws.write_number(row_index, 12, 0.0, formats["percent"])
    raw_ws.autofilter(1, 0, 1 + len(raw_case_rows), len(raw_headers) - 1)
    raw_ws.set_column("A:A", 17)
    raw_ws.set_column("B:D", 9)
    raw_ws.set_column("E:E", 11)
    raw_ws.set_column("F:M", 18)

    raw_summary_start = 1
    raw_summary_col = 14
    raw_ws.write(raw_summary_start, raw_summary_col, "Metric", formats["header"])
    raw_ws.write(raw_summary_start, raw_summary_col + 1, "llm-d / Raw", formats["header"])
    raw_ws.write(raw_summary_start, raw_summary_col + 2, "Delta", formats["header"])
    raw_ws.write(raw_summary_start, raw_summary_col + 3, "Parity", formats["header"])
    raw_metric_map = {row[0]: row for row in raw_summary_rows}
    selected_raw = ["Output throughput", "p99 TTFT", "p99 TPOT", "p99 E2E"]
    for offset, metric in enumerate(selected_raw, 1):
        ratio = number(raw_metric_map[metric][1])
        raw_ws.write(raw_summary_start + offset, raw_summary_col, metric, formats["text"])
        raw_ws.write_number(raw_summary_start + offset, raw_summary_col + 1, ratio, formats["ratio"])
        raw_ws.write_formula(
            raw_summary_start + offset,
            raw_summary_col + 2,
            f"=P{raw_summary_start + offset + 1}-1",
            formats["percent"],
            ratio - 1,
        )
        raw_ws.write_number(raw_summary_start + offset, raw_summary_col + 3, 0.0, formats["percent"])

    raw_group_start = 8
    group_rows = []
    for row_values in raw_group_rows:
        group_rows.append(
            [
                row_values[0], number(row_values[1]), integer(row_values[2]),
                number(row_values[3]), number(row_values[4]), number(row_values[5]), number(row_values[6]),
            ]
        )
    write_table(
        raw_ws,
        raw_group_start,
        raw_summary_col,
        ["Dimension", "Group", "Cases", "Throughput", "p99 TTFT", "p99 TPOT", "p99 E2E"],
        group_rows,
        formats,
        [12, 10, 8, 13, 12, 12, 12],
    )

    raw_delta_chart = workbook.add_chart({"type": "column"})
    raw_delta_chart.add_series(
        {
            "name": "Delta",
            "categories": ["01_Raw_vs_llmd", raw_summary_start + 1, raw_summary_col, raw_summary_start + 4, raw_summary_col],
            "values": ["01_Raw_vs_llmd", raw_summary_start + 1, raw_summary_col + 2, raw_summary_start + 4, raw_summary_col + 2],
            "fill": {"color": BLUE},
            "border": {"none": True},
            "data_labels": {"value": True, "num_format": "0.0%"},
        }
    )
    add_baseline(workbook, raw_delta_chart, "01_Raw_vs_llmd", raw_summary_start + 1, raw_summary_start + 4, raw_summary_col, raw_summary_col + 3)
    configure_chart(raw_delta_chart, "Raw vs llm-d: Overall Difference", "(llm-d / Raw) - 1", legend=False, y_min=-0.06, y_max=0.06)
    raw_ws.insert_chart("O21", raw_delta_chart)

    raw_case_chart = workbook.add_chart({"type": "column"})
    raw_case_chart.add_series(
        {
            "name": "Throughput delta",
            "categories": ["01_Raw_vs_llmd", 2, 0, 25, 0],
            "values": ["01_Raw_vs_llmd", 2, 7, 25, 7],
            "fill": {"color": BLUE},
            "border": {"none": True},
        }
    )
    add_baseline(workbook, raw_case_chart, "01_Raw_vs_llmd", 2, 25, 0, 12)
    configure_chart(raw_case_chart, "Raw vs llm-d: Per-case Throughput Delta", "(llm-d / Raw) - 1", legend=False, y_min=-0.06, y_max=0.06)
    raw_case_chart.set_x_axis({"label_position": "low", "num_font": {"rotation": -45, "size": 8}})
    raw_ws.insert_chart("O40", raw_case_chart)

    agg_ws = workbook.add_worksheet("02_Agg_vs_1P1D")
    agg_ws.freeze_panes(2, 0)
    agg_ws.write("A1", "Aggregate versus llm-d 1P1D (strict same-node cases)", formats["title"])
    agg_headers = ["Case", "ISL", "OSL", "C", "Aggregate out", "P/D out", "Out ratio", "p99 TTFT ratio", "p99 TPOT ratio", "p99 E2E ratio", "Parity"]
    for col, header in enumerate(agg_headers):
        agg_ws.write(1, col, header, formats["header"])
    for row_index, row_values in enumerate(agg_case_rows, 2):
        isl, osl, concurrency = integer(row_values[0]), integer(row_values[1]), integer(row_values[2])
        values = [
            case_label(isl, osl, concurrency), isl, osl, concurrency,
            number(row_values[3]), number(row_values[4]), number(row_values[5]),
            number(row_values[6]), number(row_values[7]), number(row_values[8]), 1.0,
        ]
        for col, value in enumerate(values):
            fmt = formats["text"] if col == 0 else (formats["integer"] if col in (1, 2, 3) else formats["ratio"])
            agg_ws.write(row_index, col, value, fmt)
    agg_ws.autofilter(1, 0, 1 + len(agg_case_rows), len(agg_headers) - 1)
    agg_ws.set_column("A:A", 17)
    agg_ws.set_column("B:D", 9)
    agg_ws.set_column("E:K", 17)

    agg_summary_col = 12
    agg_ws.write(1, agg_summary_col, "Metric", formats["header"])
    agg_ws.write(1, agg_summary_col + 1, "Aggregate/P-D", formats["header"])
    agg_ws.write(1, agg_summary_col + 2, "Aggregate advantage", formats["header"])
    agg_ws.write(1, agg_summary_col + 3, "Parity", formats["header"])
    agg_metric_map = {row[0]: row for row in agg_summary_rows}
    selected_agg = ["Output throughput", "p99 TTFT", "p99 TPOT", "p99 E2E"]
    for offset, metric in enumerate(selected_agg, 2):
        ratio = number(agg_metric_map[metric][3])
        advantage = ratio if metric == "Output throughput" else 1 / ratio
        agg_ws.write(offset, agg_summary_col, metric, formats["text"])
        agg_ws.write_number(offset, agg_summary_col + 1, ratio, formats["ratio"])
        agg_ws.write_number(offset, agg_summary_col + 2, advantage, formats["ratio"])
        agg_ws.write_number(offset, agg_summary_col + 3, 1.0, formats["ratio"])
    agg_ws.write(7, agg_summary_col, "Advantage converts latency ratios to P-D/Aggregate, so values above 1 favor Aggregate.", formats["note"])
    agg_ws.merge_range(7, agg_summary_col, 8, agg_summary_col + 3, "Advantage converts latency ratios to P-D/Aggregate, so values above 1 favor Aggregate.", formats["note"])

    agg_adv_chart = workbook.add_chart({"type": "column"})
    agg_adv_chart.add_series(
        {
            "name": "Aggregate relative advantage",
            "categories": ["02_Agg_vs_1P1D", 2, agg_summary_col, 5, agg_summary_col],
            "values": ["02_Agg_vs_1P1D", 2, agg_summary_col + 2, 5, agg_summary_col + 2],
            "fill": {"color": BLUE},
            "border": {"none": True},
            "data_labels": {"value": True, "num_format": "0.00x"},
        }
    )
    add_baseline(workbook, agg_adv_chart, "02_Agg_vs_1P1D", 2, 5, agg_summary_col, agg_summary_col + 3)
    configure_chart(agg_adv_chart, "Aggregate Relative Advantage (>1 favors Aggregate)", "Advantage factor; latency inverted", legend=False, y_min=0, y_max=1.7)
    agg_ws.insert_chart("M11", agg_adv_chart)

    agg_trade_chart = ratio_chart(
        workbook,
        "02_Agg_vs_1P1D",
        2,
        11,
        0,
        [("p99 TTFT", 7, BLUE), ("p99 TPOT", 8, ORANGE)],
        10,
        "Aggregate/P-D: Per-case TTFT and TPOT Ratios",
        "Aggregate / P-D",
        0,
        4.1,
    )
    agg_ws.insert_chart("M30", agg_trade_chart)

    topology_ws = workbook.add_worksheet("03_2P2D_vs_1P3D")
    topology_ws.freeze_panes(2, 0)
    topology_ws.write("A1", "Equal-resource 2P2D versus 1P3D", formats["title"])
    topology_headers = ["Case", "ISL", "OSL", "C", "2P2D out", "1P3D out", "Out ratio", "p99 TTFT ratio", "p99 TPOT ratio", "p99 E2E ratio", "Parity"]
    for col, header in enumerate(topology_headers):
        topology_ws.write(1, col, header, formats["header"])
    topology_records = []
    for row_index, row_values in enumerate(topology_case_rows, 2):
        isl, osl, concurrency = integer(row_values[0]), integer(row_values[1]), integer(row_values[2])
        record = [
            case_label(isl, osl, concurrency), isl, osl, concurrency,
            number(row_values[3]), number(row_values[4]), number(row_values[5]),
            number(row_values[6]), number(row_values[7]), number(row_values[8]), 1.0,
        ]
        topology_records.append(record)
        for col, value in enumerate(record):
            fmt = formats["text"] if col == 0 else (formats["integer"] if col in (1, 2, 3) else formats["ratio"])
            topology_ws.write(row_index, col, value, fmt)
    topology_ws.autofilter(1, 0, 1 + len(topology_records), len(topology_headers) - 1)
    topology_ws.set_column("A:A", 17)
    topology_ws.set_column("B:D", 9)
    topology_ws.set_column("E:K", 17)

    topology_group_col = 12
    topology_groups = []
    for row_values in topology_group_rows:
        topology_groups.append(
            [row_values[0], number(row_values[1]), number(row_values[2]), number(row_values[3]), number(row_values[4]), number(row_values[5])]
        )
    write_table(
        topology_ws,
        1,
        topology_group_col,
        ["Dimension", "Group", "Throughput", "p99 TTFT", "p99 TPOT", "p99 E2E"],
        topology_groups,
        formats,
        [12, 10, 14, 13, 13, 13],
    )
    for row_idx in range(2, 2 + len(topology_groups)):
        topology_ws.write_number(row_idx, topology_group_col + 6, 1.0, formats["ratio"])
    topology_ws.write(1, topology_group_col + 6, "Parity", formats["header"])

    heatmap_row = 14
    heatmap_col = topology_group_col
    topology_ws.write(heatmap_row, heatmap_col, "Throughput heatmap: 1P3D / 2P2D", formats["section"])
    topology_ws.write(heatmap_row + 1, heatmap_col, "ISL / OSL", formats["header"])
    concurrencies = [1, 8, 32, 64]
    for offset, concurrency in enumerate(concurrencies, 1):
        topology_ws.write_number(heatmap_row + 1, heatmap_col + offset, concurrency, formats["header"])
    heatmap_keys = [(1024, 128), (1024, 1024), (8192, 128), (8192, 1024), (16384, 128), (16384, 1024)]
    record_map = {(record[1], record[2], record[3]): record[6] for record in topology_records}
    for row_offset, (isl, osl) in enumerate(heatmap_keys, 2):
        topology_ws.write(heatmap_row + row_offset, heatmap_col, f"I{isl // 1024}K / O{osl}", formats["text"])
        for col_offset, concurrency in enumerate(concurrencies, 1):
            topology_ws.write_number(
                heatmap_row + row_offset,
                heatmap_col + col_offset,
                record_map[(isl, osl, concurrency)],
                formats["ratio"],
            )
    topology_ws.conditional_format(
        heatmap_row + 2,
        heatmap_col + 1,
        heatmap_row + 1 + len(heatmap_keys),
        heatmap_col + len(concurrencies),
        {
            "type": "3_color_scale",
            "min_type": "num", "min_value": 0.5, "min_color": LIGHT_BLUE,
            "mid_type": "num", "mid_value": 1.0, "mid_color": "#FFFFFF",
            "max_type": "num", "max_value": 1.4, "max_color": LIGHT_ORANGE,
        },
    )
    topology_ws.write(heatmap_row + 9, heatmap_col, "Blue favors 2P2D; orange favors 1P3D; white is parity.", formats["note"])
    topology_ws.merge_range(heatmap_row + 9, heatmap_col, heatmap_row + 9, heatmap_col + 4, "Blue favors 2P2D; orange favors 1P3D; white is parity.", formats["note"])

    osl_rows = [index for index, row in enumerate(topology_groups, 2) if row[0] == "OSL"]
    c_rows = [index for index, row in enumerate(topology_groups, 2) if row[0] == "C"]
    osl_chart = ratio_chart(
        workbook, "03_2P2D_vs_1P3D", min(osl_rows), max(osl_rows),
        topology_group_col + 1, [("Throughput", topology_group_col + 2, GREEN)],
        topology_group_col + 6,
        "1P3D/2P2D Throughput by Output Length", "1P3D / 2P2D", 0.5, 1.15,
    )
    topology_ws.insert_chart("M27", osl_chart)
    c_chart = ratio_chart(
        workbook, "03_2P2D_vs_1P3D", min(c_rows), max(c_rows),
        topology_group_col + 1, [("Throughput", topology_group_col + 2, GREEN)],
        topology_group_col + 6,
        "1P3D/2P2D Throughput by Concurrency", "1P3D / 2P2D", 0.5, 1.1,
    )
    topology_ws.insert_chart("M46", c_chart)

    abba_ws = workbook.add_worksheet("04_Equal_ABBA")
    abba_ws.hide_gridlines(2)
    abba_ws.write("A1", "Equal-resource Aggregate versus 2P2D ABBA", formats["title"])

    def arm_rows(rows):
        converted = []
        for row_values in rows:
            converted.append([row_values[0], row_values[1]] + [number(value) for value in row_values[2:]])
        return converted

    def mean_map(rows):
        return {row[0]: (number(row[1]), number(row[2]), number(row[3])) for row in rows}

    indep_arm_start = 2
    write_table(
        abba_ws,
        indep_arm_start,
        0,
        indep_arm_headers,
        arm_rows(indep_arm_rows),
        formats,
        [8, 12, 13, 13, 13, 13, 13, 13, 13],
    )
    shared_arm_start = 9
    write_table(
        abba_ws,
        shared_arm_start,
        0,
        shared_arm_headers,
        arm_rows(shared_arm_rows),
        formats,
        [8, 12, 13, 13, 13],
    )
    long_arm_start = 16
    write_table(
        abba_ws,
        long_arm_start,
        0,
        long_arm_headers,
        arm_rows(long_arm_rows),
        formats,
        [8, 12, 13, 13, 13, 13, 13, 13, 13],
    )

    indep_map, shared_map, long_map = mean_map(indep_mean_rows), mean_map(shared_mean_rows), mean_map(long_mean_rows)
    summary_start = 2
    summary_col = 10
    abba_ws.write(summary_start, summary_col, "Workload", formats["header"])
    abba_ws.write(summary_start, summary_col + 1, "Aggregate out tok/s", formats["header"])
    abba_ws.write(summary_start, summary_col + 2, "2P2D out tok/s", formats["header"])
    abba_ws.write(summary_start, summary_col + 3, "Aggregate/2P2D", formats["header"])
    workloads = [
        ("Independent C64", indep_map["Output throughput"]),
        ("Shared-prefix W2", shared_map["Output throughput"]),
        ("Long OSL1024", long_map["Output throughput"]),
    ]
    for offset, (name, values) in enumerate(workloads, 1):
        abba_ws.write(summary_start + offset, summary_col, name, formats["text"])
        for value_offset, value in enumerate(values):
            abba_ws.write_number(summary_start + offset, summary_col + 1 + value_offset, value, formats["ratio"])
    abba_ws.set_column(summary_col, summary_col, 22)
    abba_ws.set_column(summary_col + 1, summary_col + 3, 19)

    tail_start = 8
    abba_ws.write(tail_start, summary_col, "Workload", formats["header"])
    abba_ws.write(tail_start, summary_col + 1, "p99 TTFT Aggregate/2P2D", formats["header"])
    abba_ws.write(tail_start, summary_col + 2, "p99 TPOT Aggregate/2P2D", formats["header"])
    abba_ws.write(tail_start, summary_col + 3, "Parity", formats["header"])
    tail_rows = [
        ("Independent C64", indep_map["p99 TTFT"][2], indep_map["p99 TPOT"][2]),
        ("Long OSL1024", long_map["p99 TTFT"][2], long_map["p99 TPOT"][2]),
    ]
    for offset, (name, ttft, tpot) in enumerate(tail_rows, 1):
        abba_ws.write(tail_start + offset, summary_col, name, formats["text"])
        abba_ws.write_number(tail_start + offset, summary_col + 1, ttft, formats["ratio"])
        abba_ws.write_number(tail_start + offset, summary_col + 2, tpot, formats["ratio"])
        abba_ws.write_number(tail_start + offset, summary_col + 3, 1.0, formats["ratio"])

    confirm_start = 13
    confirm_data = [[row[0], number(row[1]), number(row[2]), number(row[3])] for row in confirm_rows]
    write_table(
        abba_ws,
        confirm_start,
        summary_col,
        confirm_headers,
        confirm_data,
        formats,
        [22, 16, 16, 20],
    )

    throughput_chart = clustered_chart(
        workbook,
        "04_Equal_ABBA",
        summary_start + 1,
        summary_start + 3,
        summary_col,
        [("Aggregate", summary_col + 1, BLUE), ("2P2D", summary_col + 2, ORANGE)],
        "Equal-resource Output Throughput by Workload",
        "Output tokens/s",
    )
    abba_ws.insert_chart("K25", throughput_chart)
    tail_chart = ratio_chart(
        workbook,
        "04_Equal_ABBA",
        tail_start + 1,
        tail_start + 2,
        summary_col,
        [("p99 TTFT", summary_col + 1, BLUE), ("p99 TPOT", summary_col + 2, ORANGE)],
        summary_col + 3,
        "Aggregate/2P2D Tail-latency Ratios",
        "Aggregate / 2P2D; lower is better",
        0,
        3.5,
    )
    abba_ws.insert_chart("K44", tail_chart)

    failure_ws = workbook.add_worksheet("05_3P1D_Failure")
    failure_ws.hide_gridlines(2)
    failure_ws.write("A1", "3P1D Reproduced Liveness Failure", formats["title"])
    failure_ws.write("A2", "Failure evidence only; no performance comparison or throughput ratio is valid.", formats["note"])
    failure_data = []
    for row_values in failure_rows:
        if row_values[0] in ("No-token-progress interval", "Missing completions"):
            failure_data.append([row_values[0], number(row_values[1]), number(row_values[2])])
    write_table(failure_ws, 3, 0, ["Evidence", "Attempt 1", "Attempt 2"], failure_data, formats, [30, 15, 15])
    progress_chart = clustered_chart(
        workbook, "05_3P1D_Failure", 4, 4, 0,
        [("Attempt 1", 1, BLUE), ("Attempt 2", 2, ORANGE)],
        "3P1D No-token-progress Interval", "Seconds",
    )
    failure_ws.insert_chart("A9", progress_chart)
    missing_chart = clustered_chart(
        workbook, "05_3P1D_Failure", 5, 5, 0,
        [("Attempt 1", 1, BLUE), ("Attempt 2", 2, ORANGE)],
        "3P1D Missing Response Completions", "Response lifecycles",
    )
    failure_ws.insert_chart("J9", missing_chart)

    dashboard = workbook.add_worksheet("06_Dashboard")
    dashboard.hide_gridlines(2)
    dashboard.set_tab_color("#1F4E78")
    dashboard.write("A1", "Qwen3-32B P/D and Topology Benchmark Dashboard", formats["title"])
    dashboard.write("A2", "Dashed lines mark parity. Throughput is higher-is-better; latency is lower-is-better unless a chart explicitly says values were inverted.", formats["note"])
    dashboard.set_column("A:Q", 12)

    dashboard_raw_delta = workbook.add_chart({"type": "column"})
    dashboard_raw_delta.add_series(
        {
            "name": "Delta",
            "categories": ["01_Raw_vs_llmd", raw_summary_start + 1, raw_summary_col, raw_summary_start + 4, raw_summary_col],
            "values": ["01_Raw_vs_llmd", raw_summary_start + 1, raw_summary_col + 2, raw_summary_start + 4, raw_summary_col + 2],
            "fill": {"color": BLUE},
            "border": {"none": True},
            "data_labels": {"value": True, "num_format": "0.0%"},
        }
    )
    add_baseline(workbook, dashboard_raw_delta, "01_Raw_vs_llmd", raw_summary_start + 1, raw_summary_start + 4, raw_summary_col, raw_summary_col + 3)
    configure_chart(dashboard_raw_delta, "1. Raw vs llm-d: Overall Difference", "(llm-d / Raw) - 1", legend=False, y_min=-0.06, y_max=0.06)
    dashboard.insert_chart("A4", dashboard_raw_delta)

    dashboard_raw_cases = workbook.add_chart({"type": "column"})
    dashboard_raw_cases.add_series(
        {
            "name": "Throughput delta",
            "categories": ["01_Raw_vs_llmd", 2, 0, 25, 0],
            "values": ["01_Raw_vs_llmd", 2, 7, 25, 7],
            "fill": {"color": BLUE},
            "border": {"none": True},
        }
    )
    add_baseline(workbook, dashboard_raw_cases, "01_Raw_vs_llmd", 2, 25, 0, 12)
    configure_chart(dashboard_raw_cases, "2. Raw vs llm-d: Per-case Throughput Delta", "(llm-d / Raw) - 1", legend=False, y_min=-0.06, y_max=0.06)
    dashboard_raw_cases.set_x_axis({"label_position": "low", "num_font": {"rotation": -45, "size": 8}})
    dashboard.insert_chart("J4", dashboard_raw_cases)

    dashboard_agg_adv = workbook.add_chart({"type": "column"})
    dashboard_agg_adv.add_series(
        {
            "name": "Aggregate relative advantage",
            "categories": ["02_Agg_vs_1P1D", 2, agg_summary_col, 5, agg_summary_col],
            "values": ["02_Agg_vs_1P1D", 2, agg_summary_col + 2, 5, agg_summary_col + 2],
            "fill": {"color": BLUE},
            "border": {"none": True},
            "data_labels": {"value": True, "num_format": "0.00x"},
        }
    )
    add_baseline(workbook, dashboard_agg_adv, "02_Agg_vs_1P1D", 2, 5, agg_summary_col, agg_summary_col + 3)
    configure_chart(dashboard_agg_adv, "3. Aggregate Relative Advantage", ">1 favors Aggregate; latency inverted", legend=False, y_min=0, y_max=1.7)
    dashboard.insert_chart("A23", dashboard_agg_adv)

    dashboard_agg_trade = ratio_chart(
        workbook, "02_Agg_vs_1P1D", 2, 11, 0,
        [("p99 TTFT", 7, BLUE), ("p99 TPOT", 8, ORANGE)],
        10,
        "4. Aggregate/P-D: Per-case TTFT and TPOT", "Aggregate / P-D", 0, 4.1,
    )
    dashboard.insert_chart("J23", dashboard_agg_trade)

    dashboard_osl = ratio_chart(
        workbook, "03_2P2D_vs_1P3D", min(osl_rows), max(osl_rows),
        topology_group_col + 1, [("Throughput", topology_group_col + 2, GREEN)],
        topology_group_col + 6,
        "5. 1P3D/2P2D Throughput by OSL", "1P3D / 2P2D", 0.5, 1.15,
    )
    dashboard.insert_chart("A42", dashboard_osl)

    dashboard_c = ratio_chart(
        workbook, "03_2P2D_vs_1P3D", min(c_rows), max(c_rows),
        topology_group_col + 1, [("Throughput", topology_group_col + 2, GREEN)],
        topology_group_col + 6,
        "6. 1P3D/2P2D Throughput by Concurrency", "1P3D / 2P2D", 0.5, 1.1,
    )
    dashboard.insert_chart("J42", dashboard_c)

    dashboard_throughput = clustered_chart(
        workbook, "04_Equal_ABBA", summary_start + 1, summary_start + 3, summary_col,
        [("Aggregate", summary_col + 1, BLUE), ("2P2D", summary_col + 2, ORANGE)],
        "7. Equal-resource Throughput by Workload", "Output tokens/s",
    )
    dashboard.insert_chart("A61", dashboard_throughput)

    dashboard_tail = ratio_chart(
        workbook, "04_Equal_ABBA", tail_start + 1, tail_start + 2, summary_col,
        [("p99 TTFT", summary_col + 1, BLUE), ("p99 TPOT", summary_col + 2, ORANGE)],
        summary_col + 3,
        "8. Aggregate/2P2D Tail-latency Ratios", "Aggregate / 2P2D; lower is better", 0, 3.5,
    )
    dashboard.insert_chart("J61", dashboard_tail)

    workbook.close()


def main():
    parser = argparse.ArgumentParser(description="Generate Excel charts for the Qwen3-32B Intel B60 P/D benchmark report.")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).with_name("qwen3-32b-intel-b60-benchmark.md"),
        help="Source Markdown report",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("qwen3-32b-intel-b60-benchmark-charts.xlsx"),
        help="Output XLSX workbook",
    )
    args = parser.parse_args()
    build_workbook(args.report.resolve(), args.output.resolve())
    print(args.output.resolve())


if __name__ == "__main__":
    main()
