#!/usr/bin/env python3
"""Run perftest and OSU benchmarks between node1 and node2 over SSH,
parse the raw outputs, and write CSVs into results/csv/<timestamp>/.

Usage: python3 scripts/run_benchmarks.py
"""

import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

NODE1 = "192.168.122.38"  # 10.0.0.1 on the lab network
NODE2 = "192.168.122.47"  # 10.0.0.2
SSH_KEY = str(Path.home() / ".ssh" / "ai_fabric_lab")
OSU_BIN = "~/src/osu-micro-benchmarks-7.4/c/mpi"
REPO = Path(__file__).resolve().parent.parent

MPI_COMMON = "mpirun -np 2 --host node1,node2 --mca oob_tcp_if_include enp2s0"
MPI_TCP = "--mca pml ob1 --mca btl tcp,self --mca btl_tcp_if_include enp2s0"
# GID index 0 (IPv6 link-local): kernel 6.8 rxe drops RoCEv2/IPv4 UD
# packets before they reach UCX -- see docs/mpi.md "Root Cause Analysis".
MPI_RDMA = ("--mca pml ucx -x UCX_TLS=rc_verbs,ud_verbs,self,sm "
            "-x UCX_NET_DEVICES=rxe0:1 -x UCX_IB_GID_INDEX=0")


def ssh(host, cmd, timeout=900):
    return subprocess.run(
        ["ssh", "-i", SSH_KEY, f"ubuntu@{host}", cmd],
        capture_output=True, text=True, timeout=timeout)


def numeric_rows(text, ncols):
    """Return the whitespace-separated lines made only of numbers."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < ncols:
            continue
        try:
            rows.append([float(p) for p in parts])
        except ValueError:
            continue
    return rows


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  -> {path.relative_to(REPO)} ({len(rows)} rows)")


def run_perftest(tool, iters, outdir):
    """perftest server on node1, client on node2, all message sizes (-a)."""
    print(f"[perftest] {tool}")
    ssh(NODE1, f"pkill -x {tool} || true", timeout=15)
    ssh(NODE2, f"pkill -x {tool} || true", timeout=15)
    server = subprocess.Popen(
        ["ssh", "-i", SSH_KEY, f"ubuntu@{NODE1}",
         f"timeout 800 {tool} -a -d rxe0 -x 1 -n {iters}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    out = ssh(NODE2, f"timeout 800 {tool} -a -d rxe0 -x 1 -n {iters} 10.0.0.1")
    server.wait(timeout=30)
    (outdir / f"{tool}.txt").write_text(out.stdout + out.stderr)
    if out.returncode != 0:
        print(f"  !! {tool} failed (exit {out.returncode}), raw output kept")
        return
    if "lat" in tool:
        rows = [(int(r[0]), r[4], r[5], r[2], r[3])
                for r in numeric_rows(out.stdout, 9)]
        write_csv(outdir / f"{tool}.csv",
                  ["size_bytes", "lat_typical_us", "lat_avg_us",
                   "lat_min_us", "lat_max_us"], rows)
    else:
        rows = [(int(r[0]), r[2], r[3])
                for r in numeric_rows(out.stdout, 5)]
        write_csv(outdir / f"{tool}.csv",
                  ["size_bytes", "bw_peak_MBps", "bw_avg_MBps"], rows)


def run_osu(bench, transport, mpi_opts, value_name, outdir):
    """One OSU benchmark through mpirun on node1."""
    name = f"{Path(bench).name}_{transport}"
    print(f"[osu] {name}")
    out = ssh(NODE1, f"timeout 500 {MPI_COMMON} {mpi_opts} {OSU_BIN}/{bench}")
    (outdir / f"{name}.txt").write_text(out.stdout + out.stderr)
    if out.returncode != 0:
        print(f"  !! {name} failed (exit {out.returncode}), raw output kept")
        return
    rows = [(int(r[0]), r[1]) for r in numeric_rows(out.stdout, 2)]
    write_csv(outdir / f"{name}.csv", ["size_bytes", value_name], rows)


def main():
    check = ssh(NODE1, "rdma link show", timeout=15)
    if "rxe0" not in check.stdout:
        sys.exit("rxe0 missing on node1 (rdma link add is not "
                 "reboot-persistent) -- recreate it before benchmarking")

    outdir = REPO / "results" / "csv" / datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir.mkdir(parents=True)
    print(f"writing to {outdir.relative_to(REPO)}")

    # -a sweeps sizes up to 8 MiB; Soft-RoCE tops out near 100 MB/s, so
    # iteration counts are kept low enough for each sweep to finish.
    run_perftest("ib_send_lat", 200, outdir)
    run_perftest("ib_write_bw", 300, outdir)
    run_perftest("ib_read_bw", 300, outdir)

    for transport, opts in [("tcp", MPI_TCP), ("rdma", MPI_RDMA)]:
        run_osu("pt2pt/standard/osu_latency", transport, opts,
                "latency_us", outdir)
        run_osu("pt2pt/standard/osu_bw", transport, opts,
                "bandwidth_MBps", outdir)
        run_osu("collective/blocking/osu_allreduce", transport, opts,
                "latency_us", outdir)

    print("done")


if __name__ == "__main__":
    main()
