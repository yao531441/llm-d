#!/usr/bin/env python3

import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


BLUE = "#4472C4"
ORANGE = "#ED7D31"
GREEN = "#70AD47"
GRAY = "#7F7F7F"
RED = "#C00000"
ISL_STYLES = {
    1024: (BLUE, "1K"),
    8192: (ORANGE, "8K"),
    16384: (GREEN, "16K"),
}

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "axes.edgecolor": "#D0D7DE",
        "axes.labelcolor": "#24292F",
        "axes.titlecolor": "#24292F",
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "xtick.color": "#57606A",
        "ytick.color": "#57606A",
        "grid.color": "#D8DEE4",
        "grid.linewidth": 0.7,
        "legend.frameon": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "svg.hashsalt": "llmd-qwen3-32b-intel-b60",
    }
)


def section(text, start, end):
    begin = text.index(start)
    return text[begin : text.index(end, begin)]


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
        if len(block) >= 3:
            tables.append((split_row(block[0]), [split_row(line) for line in block[2:]]))
    return tables


def pick_table(text, required_headers):
    for headers, rows in extract_tables(text):
        if all(header in headers for header in required_headers):
            return headers, rows
    raise ValueError(f"table not found: {required_headers}")


def number(value):
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", "").replace("%", ""))
    if not match:
        raise ValueError(f"numeric value not found: {value}")
    return float(match.group(0))


def integer(value):
    return int(number(value))


def short_tokens(value):
    return f"{value // 1024}K" if value >= 1024 else str(value)


def case_label(isl, osl, concurrency):
    return f"I{short_tokens(isl)}/O{short_tokens(osl)}/C{concurrency}"


def extract_data(text):
    raw_text = section(text, "## 6. Canonical Raw versus llm-d 1P1D", "## 7.")
    _, raw_rows = pick_table(raw_text, ["Raw out tok/s", "llm-d out tok/s"])

    aggregate_text = section(text, "## 7. Aggregate baseline", "## 8.")
    _, aggregate_rows = pick_table(aggregate_text, ["Aggregate out", "llm-d P/D out"])

    topology_text = section(text, "## 8. Equal-resource 2P2D versus 1P3D", "## 9.")
    _, topology_rows = pick_table(topology_text, ["2P2D out", "1P3D out"])

    independent_text = section(text, "### 10.2 Independent-workload arms", "### 10.3")
    independent_headers, independent_rows = pick_table(
        independent_text, ["Arm", "Topology", "Out tok/s"]
    )
    shared_text = section(text, "### 10.3 Shared-prefix arms", "### 10.4")
    shared_headers, shared_rows = pick_table(
        shared_text, ["Arm", "Topology", "Out tok/s"]
    )
    long_text = section(text, "### 10.4 Long-output arms", "## 11.")
    long_headers, long_rows = pick_table(
        long_text, ["Arm", "Topology", "Out tok/s"]
    )

    failure_text = section(text, "## 9. 3P1D capacity/liveness failure", "## 10.")
    failure_headers, failure_rows = pick_table(
        failure_text, ["Evidence", "First attempt", "Second attempt"]
    )

    expected = {
        "Raw/llm-d": (len(raw_rows), 24),
        "Aggregate/P-D": (len(aggregate_rows), 10),
        "2P2D/1P3D": (len(topology_rows), 24),
        "Independent ABBA": (len(independent_rows), 4),
        "Shared-prefix ABBA": (len(shared_rows), 4),
        "Long-output ABBA": (len(long_rows), 4),
    }
    for label, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ValueError(f"{label}: expected {wanted} rows, found {actual}")

    raw = []
    for row in raw_rows:
        raw_ttft = number(row[7])
        raw_tpot = number(row[9])
        raw.append(
            {
                "isl": integer(row[0]),
                "osl": integer(row[1]),
                "c": integer(row[2]),
                "out_ratio": 1 + number(row[6]) / 100,
                "ttft_ratio": number(row[8]) / raw_ttft,
                "tpot_ratio": number(row[10]) / raw_tpot,
            }
        )

    aggregate = [
        {
            "isl": integer(row[0]),
            "osl": integer(row[1]),
            "c": integer(row[2]),
            "out_ratio": number(row[5]),
            "ttft_ratio": number(row[6]),
            "tpot_ratio": number(row[7]),
            "e2e_ratio": number(row[8]),
        }
        for row in aggregate_rows
    ]
    topology = [
        {
            "isl": integer(row[0]),
            "osl": integer(row[1]),
            "c": integer(row[2]),
            "out_ratio": number(row[5]),
            "ttft_ratio": number(row[6]),
            "tpot_ratio": number(row[7]),
            "e2e_ratio": number(row[8]),
        }
        for row in topology_rows
    ]

    def arm_records(headers, rows):
        records = []
        for row in rows:
            record = {"arm": row[0], "topology": row[1]}
            for column, value in zip(headers[2:], row[2:]):
                record[column] = number(value)
            records.append(record)
        return records

    return {
        "raw": raw,
        "aggregate": aggregate,
        "topology": topology,
        "independent": arm_records(independent_headers, independent_rows),
        "shared": arm_records(shared_headers, shared_rows),
        "long": arm_records(long_headers, long_rows),
        "failure": (failure_headers, failure_rows),
    }


def style_axis(axis):
    axis.grid(axis="y")
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.set_axisbelow(True)


def plot_ratio_curves(axis, records, metric, title, ylabel, limits):
    concurrencies = sorted({record["c"] for record in records})
    for isl in sorted(ISL_STYLES):
        color, isl_label = ISL_STYLES[isl]
        for osl, linestyle, marker in [(128, "-", "o"), (1024, "--", "s")]:
            subset = sorted(
                [
                    record
                    for record in records
                    if record["isl"] == isl and record["osl"] == osl
                ],
                key=lambda record: record["c"],
            )
            axis.plot(
                [record["c"] for record in subset],
                [record[metric] for record in subset],
                label=f"I{isl_label}/O{short_tokens(osl)}",
                color=color,
                linestyle=linestyle,
                linewidth=2,
                marker=marker,
                markersize=5,
            )
    axis.axhline(1.0, color=GRAY, linestyle=":", linewidth=1.5, label="Parity")
    axis.set_title(title)
    axis.set_xlabel("Concurrency")
    axis.set_ylabel(ylabel)
    axis.set_xticks(concurrencies)
    axis.set_xlim(0, 66)
    axis.set_ylim(*limits)
    style_axis(axis)


def save_figure(fig, output):
    fig.savefig(
        output,
        format="svg",
        bbox_inches="tight",
        metadata={
            "Date": None,
            "Creator": "generate_qwen3_32b_intel_b60_charts.py",
        },
    )
    plt.close(fig)
    svg = output.read_text(encoding="utf-8")
    output.write_text(
        "\n".join(line.rstrip() for line in svg.splitlines()) + "\n",
        encoding="utf-8",
    )


def raw_figure(records, output):
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8))
    specs = [
        ("out_ratio", "Output throughput", "llm-d / Raw", (0.94, 1.06)),
        ("ttft_ratio", "p99 TTFT", "llm-d / Raw (lower is better)", (0.95, 1.10)),
        ("tpot_ratio", "p99 TPOT", "llm-d / Raw (lower is better)", (0.90, 1.15)),
    ]
    for axis, spec in zip(axes, specs):
        plot_ratio_curves(axis, records, *spec)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=7, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Raw P/D vs llm-d 1P1D: concurrency curves", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0.09, 1, 0.94))
    save_figure(fig, output)


def aggregate_figure(records, output):
    labels = [case_label(row["isl"], row["osl"], row["c"]) for row in records]
    positions = np.arange(len(records))
    fig, axes = plt.subplots(2, 1, figsize=(13.5, 8.5))

    axes[0].bar(positions, [row["out_ratio"] for row in records], color=BLUE)
    axes[0].axhline(1.0, color=GRAY, linestyle=":", linewidth=1.5)
    axes[0].set_title("Output throughput ratio (Aggregate / P/D)")
    axes[0].set_ylabel("Aggregate / P/D")
    axes[0].set_ylim(0, 1.7)
    axes[0].set_xticks(positions, labels, rotation=35, ha="right")
    style_axis(axes[0])

    width = 0.24
    for offset, (metric, label, color) in enumerate(
        [
            ("ttft_ratio", "p99 TTFT", BLUE),
            ("tpot_ratio", "p99 TPOT", ORANGE),
            ("e2e_ratio", "p99 E2E", GREEN),
        ]
    ):
        axes[1].bar(
            positions + (offset - 1) * width,
            [row[metric] for row in records],
            width,
            label=label,
            color=color,
        )
    axes[1].axhline(1.0, color=GRAY, linestyle=":", linewidth=1.5)
    axes[1].set_title("p99 latency ratios (Aggregate / P/D)")
    axes[1].set_ylabel("Aggregate / P/D")
    axes[1].set_ylim(0, 4.1)
    axes[1].set_xticks(positions, labels, rotation=35, ha="right")
    axes[1].legend(loc="upper left", ncol=3)
    style_axis(axes[1])

    fig.suptitle(
        "Aggregate vs 1P1D: ten strict same-node pairs",
        fontsize=15,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    save_figure(fig, output)


def topology_figure(records, output):
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    specs = [
        ("out_ratio", "Output throughput", "1P3D / 2P2D", (0.45, 1.40)),
        ("ttft_ratio", "p99 TTFT", "1P3D / 2P2D (lower is better)", (0.50, 2.00)),
        ("tpot_ratio", "p99 TPOT", "1P3D / 2P2D (lower is better)", (0.90, 1.40)),
        ("e2e_ratio", "p99 E2E", "1P3D / 2P2D (lower is better)", (0.60, 2.00)),
    ]
    for axis, spec in zip(axes.flat, specs):
        plot_ratio_curves(axis, records, *spec)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=7, bbox_to_anchor=(0.5, 0.005))
    fig.suptitle("Equal-resource 1P3D vs 2P2D: concurrency curves", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
    save_figure(fig, output)


def abba_figure(data, output):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    for axis, (key, title) in zip(
        axes,
        [
            ("independent", "Independent C64"),
            ("shared", "Shared-prefix W2"),
            ("long", "Long-output O1K"),
        ],
    ):
        records = data[key]
        labels = [f'{row["arm"]}\n{row["topology"]}' for row in records]
        colors = [BLUE if row["topology"] == "Aggregate" else ORANGE for row in records]
        values = [row["Out tok/s"] for row in records]
        bars = axis.bar(np.arange(4), values, color=colors)
        axis.bar_label(bars, fmt="%.1f", padding=3, fontsize=8)
        axis.set_xticks(np.arange(4), labels)
        axis.set_title(title)
        axis.set_ylabel("Output tokens/s")
        axis.set_ylim(0, max(values) * 1.22)
        style_axis(axis)
    fig.suptitle(
        "Equal-resource ABBA: retain every measured arm",
        fontsize=15,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    save_figure(fig, output)


def failure_figure(failure, output):
    _, rows = failure
    by_evidence = {row[0]: row for row in rows}
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    for axis, (key, title, ylabel) in zip(
        axes,
        [
            ("No-token-progress interval", "No-token-progress interval", "Seconds"),
            ("Missing completions", "Missing response completions", "Lifecycles"),
        ],
    ):
        row = by_evidence[key]
        values = [number(row[1]), number(row[2])]
        bars = axis.bar(["Attempt 1", "Attempt 2"], values, color=[BLUE, ORANGE])
        axis.bar_label(bars, fmt="%.0f", padding=3)
        axis.set_title(title)
        axis.set_ylabel(ylabel)
        axis.set_ylim(0, max(values) * 1.18)
        style_axis(axis)
    fig.suptitle(
        "3P1D: reproduced liveness failure, not a performance result",
        fontsize=14,
        fontweight="bold",
        color=RED,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    save_figure(fig, output)


def main():
    parser = argparse.ArgumentParser(description="Generate charts for the Intel B60 report.")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).with_name("qwen3-32b-intel-b60-benchmark.md"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).with_name("qwen3-32b-intel-b60-benchmark-assets"),
    )
    args = parser.parse_args()

    data = extract_data(args.report.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        ("01-raw-vs-llmd.svg", raw_figure, data["raw"]),
        ("02-aggregate-vs-pd.svg", aggregate_figure, data["aggregate"]),
        ("03-topology-curves.svg", topology_figure, data["topology"]),
        ("04-abba.svg", abba_figure, data),
        ("05-3p1d-failure.svg", failure_figure, data["failure"]),
    ]
    for filename, renderer, values in outputs:
        output = args.output_dir / filename
        renderer(values, output)
        print(output)


if __name__ == "__main__":
    main()
