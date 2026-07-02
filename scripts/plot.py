#!/usr/bin/env python3
"""Plot benchmark curves from a results/csv/<timestamp>/ run directory
(latest one by default) into plots/, and write docs/benchmark-report.md.

Usage: .venv/bin/python scripts/plot.py [results/csv/<timestamp>]
"""

import csv
import sys
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

REPO = Path(__file__).resolve().parent.parent
PLOTS = REPO / "plots"

# Chart chrome and series colors (validated reference palette, light mode).
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"
BLUE = "#2a78d6"   # series 1
AQUA = "#1baf7a"   # series 2


def read_csv(path):
    """Return (sizes, values) from the first two columns of a CSV."""
    with open(path) as f:
        rows = list(csv.reader(f))
    return ([float(r[0]) for r in rows[1:]],
            [float(r[1]) for r in rows[1:]])


def fmt_bytes(n, _pos=None):
    for unit, div in (("M", 2**20), ("K", 2**10)):
        if n >= div:
            return f"{n / div:g}{unit}"
    return f"{n:g}"


def line_chart(filename, title, ylabel, series):
    """series: list of (label, color, sizes, values); log-log axes."""
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for i, (label, color, xs, ys) in enumerate(series):
        ax.plot(xs, ys, color=color, linewidth=2, marker="o",
                markersize=5, markeredgecolor=SURFACE, markeredgewidth=1,
                label=label)
        # Direct label at the line end, in ink (not series color).
        ax.annotate(label, (xs[-1], ys[-1]),
                    xytext=(8, 6 if i == 0 else -14),
                    textcoords="offset points", fontsize=9,
                    color=INK2, clip_on=False)

    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    xs = series[0][2]
    ticks = [t for t in (1, 4, 16, 64, 256, 2**10, 2**12, 2**14, 2**16,
                         2**18, 2**20, 2**22) if xs[0] <= t <= xs[-1]]
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    ax.xaxis.set_major_formatter(FuncFormatter(fmt_bytes))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))

    ax.set_title(title, loc="left", color=INK, fontsize=12, pad=12)
    ax.set_xlabel("Message size (bytes)", color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(True, axis="y", color=GRID, linewidth=0.7)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    if len(series) > 1:
        ax.legend(loc="upper left", frameon=False, fontsize=9,
                  labelcolor=INK2)
    ax.margins(x=0.03)
    fig.tight_layout()
    fig.savefig(PLOTS / filename, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> plots/{filename}")


def rdma_vs_tcp(run, stem):
    """Load <stem>_rdma.csv and <stem>_tcp.csv as chart series."""
    series = []
    for transport, color in (("rdma", BLUE), ("tcp", AQUA)):
        path = run / f"{stem}_{transport}.csv"
        if path.exists():
            label = "RDMA (UCX / Soft-RoCE)" if transport == "rdma" else "TCP"
            series.append((label, color, *read_csv(path)))
    return series


def value_at(series, size):
    for transport_series in series:
        _, _, xs, ys = transport_series
        yield next((y for x, y in zip(xs, ys) if x == size), None)


def main():
    if len(sys.argv) > 1:
        run = REPO / sys.argv[1]
    else:
        runs = sorted((REPO / "results" / "csv").iterdir())
        if not runs:
            sys.exit("no run directory under results/csv/ -- "
                     "run scripts/run_benchmarks.py first")
        run = runs[-1]
    print(f"plotting from {run.relative_to(REPO)}")
    PLOTS.mkdir(exist_ok=True)

    allreduce = rdma_vs_tcp(run, "osu_allreduce")
    latency = rdma_vs_tcp(run, "osu_latency")
    bw = rdma_vs_tcp(run, "osu_bw")

    if allreduce:
        line_chart("osu_allreduce_rdma_vs_tcp.png",
                   "MPI allreduce latency — RDMA vs TCP (2 nodes)",
                   "Avg latency (µs)", allreduce)
    if latency:
        line_chart("osu_latency_rdma_vs_tcp.png",
                   "MPI point-to-point latency — RDMA vs TCP",
                   "Latency (µs)", latency)
    if bw:
        line_chart("osu_bw_rdma_vs_tcp.png",
                   "MPI point-to-point bandwidth — RDMA vs TCP",
                   "Bandwidth (MB/s)", bw)

    if (run / "ib_send_lat.csv").exists():
        line_chart("perftest_latency.png",
                   "Raw verbs send latency (ib_send_lat, RC)",
                   "Typical latency (µs)",
                   [("send latency", BLUE, *read_csv(run / "ib_send_lat.csv"))])
    pt_bw = [(label, color, *read_csv(run / f"{tool}.csv"))
             for label, color, tool in (("RDMA write", BLUE, "ib_write_bw"),
                                        ("RDMA read", AQUA, "ib_read_bw"))
             if (run / f"{tool}.csv").exists()]
    if pt_bw:
        line_chart("perftest_bandwidth.png",
                   "Raw verbs bandwidth (perftest, RC)",
                   "Avg bandwidth (MB/s)", pt_bw)

    write_report(run, allreduce, latency, bw)


def write_report(run, allreduce, latency, bw):
    def row(label, series, size, unit):
        vals = list(value_at(series, size))
        cells = " | ".join("-" if v is None else f"{v:,.1f}" for v in vals)
        return f"| {label} | {cells} | {unit} |"

    lines = [
        "| Metric | RDMA | TCP | Unit |",
        "|---|---|---|---|",
    ]
    if latency:
        lines.append(row("Point-to-point latency (8 B)", latency, 8, "µs"))
    if bw:
        lines.append(row("Point-to-point bandwidth (1 MiB)", bw, 2**20, "MB/s"))
    if allreduce:
        lines.append(row("Allreduce latency (8 B)", allreduce, 8, "µs"))
        lines.append(row("Allreduce latency (64 KiB)", allreduce, 2**16, "µs"))
        lines.append(row("Allreduce latency (1 MiB)", allreduce, 2**20, "µs"))
    image_paths = [
        "../plots/osu_allreduce_rdma_vs_tcp.png",
        "../plots/osu_latency_rdma_vs_tcp.png",
        "../plots/osu_bw_rdma_vs_tcp.png",
        "../plots/perftest_latency.png",
        "../plots/perftest_bandwidth.png",
    ]
    for image_path in image_paths:
        if (REPO / image_path.removeprefix("../")).exists():
            lines += ["", f"![]({image_path})"]

    out = REPO / "docs" / "benchmark-report.md"
    out.write_text("\n".join(lines))
    print(f"  -> {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
