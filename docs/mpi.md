# OpenMPI and OSU Micro-Benchmarks

This document covers the MPI layer of the lab. The goal is to run standard MPI
micro-benchmarks across `node1` and `node2`, understand which transport path is
used, and document the debugging of OpenMPI + UCX over Soft-RoCE, which
initially failed and now works after root-causing the failure to the kernel 6.8
`rxe` RoCEv2/IPv4 UD receive path (workaround: `UCX_IB_GID_INDEX=0`).



## What MPI Adds

MPI means **Message Passing Interface**. It is a standard API for distributed
programs. OpenMPI is the implementation used in this lab.

With MPI, the same binary is launched several times, possibly on several
machines. Each process receives a rank:

```text
mpirun -np 2 --host node1,node2 ./program

node1: ./program, rank 0
node2: ./program, rank 1
```

The application can then use MPI operations:

- Point-to-point operations: send/receive between ranks.
- Collective operations: communication across a group of ranks.
- `allreduce`: every rank contributes data, the data is reduced, and every rank
  receives the final reduced value.

For distributed AI training, `allreduce` is important because data-parallel
training often synchronizes gradients across nodes.

## Stack View

At this stage the RDMA verbs layer already works from section A. MPI sits above
that lower-level networking stack.

```text
OSU benchmark binary
        |
      MPI API
        |
     OpenMPI
        |
  transport selection
        |
  +------------------------------+
  | TCP over enp2s0              | works
  | TCP over NAT interface       | works, but not the lab fabric
  | UCX over rxe0 / Soft-RoCE    | works with GID index 0 (IPv6 link-local),
  |                              | fails with GID index 1 (IPv4) on kernel 6.8
  +------------------------------+
```

The intended RDMA path, now working with the GID workaround described below, is:

```text
osu_allreduce
  -> OpenMPI
    -> UCX PML
      -> libibverbs
        -> rxe0
          -> enp2s0
            -> private lab network 10.0.0.0/24
```

The working forced TCP path is:

```text
osu_allreduce
  -> OpenMPI
    -> OB1 PML
      -> TCP BTL
        -> enp2s0
          -> private lab network 10.0.0.0/24
```

## Installed Components

The MPI and build tooling are installed inside both VMs:

```bash
sudo apt update
sudo apt install -y openmpi-bin libopenmpi-dev build-essential wget tar
sudo apt install -y libucx0 libucx-dev ucx-utils
```

OSU Micro-Benchmarks are built on `node1` with the OpenMPI compiler wrappers:

```bash
cd ~/src/osu-micro-benchmarks-7.4
./configure CC=mpicc CXX=mpicxx
make -j"$(nproc)"
```

The built tree is copied to `node2` at the same path:

```bash
rsync -av ~/src/osu-micro-benchmarks-7.4/ node2:~/src/osu-micro-benchmarks-7.4/
```

Using the same path on both nodes keeps `mpirun` simple because it can start the
same executable path on each VM.

## MPI Launch Validation

The first check is not a benchmark. It only proves that OpenMPI can start one
process on each VM through SSH.

Command:

```bash
mpirun -np 2 --host node1,node2 hostname
```

Observed output:

```text
ubuntu@node1:~/src/osu-micro-benchmarks-7.4$ mpirun -np 2 --host node1,node2 hostname
node2
node1
```

This confirms:

- SSH between nodes is usable by OpenMPI.
- OpenMPI can launch remote processes on both VMs.
- The host list `node1,node2` resolves correctly.

## OSU Benchmarks Used

The OSU binaries used in this lab are:

```text
~/src/osu-micro-benchmarks-7.4/c/mpi/pt2pt/standard/osu_latency
~/src/osu-micro-benchmarks-7.4/c/mpi/pt2pt/standard/osu_bw
~/src/osu-micro-benchmarks-7.4/c/mpi/collective/blocking/osu_allreduce
```

Point-to-point latency:

```bash
mpirun -np 2 --host node1,node2 \
  ~/src/osu-micro-benchmarks-7.4/c/mpi/pt2pt/standard/osu_latency
```

Point-to-point bandwidth:

```bash
mpirun -np 2 --host node1,node2 \
  ~/src/osu-micro-benchmarks-7.4/c/mpi/pt2pt/standard/osu_bw
```

Collective allreduce:

```bash
mpirun -np 2 --host node1,node2 \
  ~/src/osu-micro-benchmarks-7.4/c/mpi/collective/blocking/osu_allreduce
```

Example allreduce output:

```text
# OSU MPI Allreduce Latency Test v7.4
# Datatype: MPI_CHAR.
# Size       Avg Latency(us)
1                      28.46
2                      64.22
4                      58.54
8                      29.52
16                     28.55
32                     30.41
```

Full raw outputs are stored under:

```text
results/mpi/osu_allreduce_default.txt
results/mpi/osu_allreduce_tcp.txt
results/mpi/osu_allreduce_ucx_rdma_attempt.txt
```

## Transport Tests

### Default OpenMPI Transport

Command:

```bash
mpirun -np 2 --host node1,node2 \
  ~/src/osu-micro-benchmarks-7.4/c/mpi/collective/blocking/osu_allreduce \
  > ~/results/osu_allreduce_default.txt 2>&1
```

This completes successfully. However, verbose OpenMPI output showed that the
default path selected TCP over the NAT/libvirt management network:

```text
[node1:16968] btl: tcp: attempting to connect() to [[2348,1],1] address 192.168.122.47 on port 1024
[node1:16968] btl:tcp: now connected to 192.168.122.47, process [[2348,1],1]
[node2:10186] btl: tcp: attempting to connect() to [[2348,1],0] address 192.168.122.38 on port 1024
[node2:10186] btl:tcp: now connected to 192.168.122.38, process [[2348,1],0]
```

Those addresses are the management/NAT addresses, not the private lab network:

```text
management/NAT: 192.168.122.38 / 192.168.122.47
lab network:    10.0.0.1 / 10.0.0.2
```

So the default successful run should not be described as RDMA.

### Forced TCP on the Lab Network

To make the completed OSU run use the private lab network, OpenMPI is forced to
use the classic TCP path on `enp2s0`.

Command:

```bash
mkdir -p ~/results

mpirun -np 2 --host node1,node2 \
  --mca pml ob1 \
  --mca btl tcp,self \
  --mca btl_tcp_if_include enp2s0 \
  ~/src/osu-micro-benchmarks-7.4/c/mpi/collective/blocking/osu_allreduce \
  > ~/results/osu_allreduce_tcp.txt 2>&1
```

Meaning of the OpenMPI options:

- `--mca pml ob1`: use OpenMPI's classic point-to-point messaging layer.
- `--mca btl tcp,self`: allow TCP for inter-node traffic and `self` for local
  loopback.
- `--mca btl_tcp_if_include enp2s0`: force TCP traffic through the private lab
  interface.

Observed output starts correctly:

```text
# OSU MPI Allreduce Latency Test v7.4
# Datatype: MPI_CHAR.
# Size       Avg Latency(us)
1                      29.44
2                      53.27
4                      50.69
8                      25.79
16                     25.81
32                     25.50
```

This is the completed MPI collective benchmark path over TCP:

```text
OpenMPI -> OB1 -> TCP -> enp2s0 -> 10.0.0.0/24
```

## What UCX Is

UCX means **Unified Communication X**. It is a communication framework used by
HPC software to select high-performance transports such as:

- shared memory for same-node communication,
- TCP,
- InfiniBand verbs,
- RoCE / Soft-RoCE through verbs.

In OpenMPI, the UCX PML can sit below MPI and above the transport-specific
libraries:

```text
MPI program
  -> OpenMPI
    -> UCX PML
      -> UCX transports
        -> tcp / rc_verbs / ud_verbs / shared memory
```

The goal was to test:

```text
OpenMPI -> UCX -> verbs -> rxe0 -> Soft-RoCE
```

OpenMPI was built with UCX support:

```text
ubuntu@node1:~/src/osu-micro-benchmarks-7.4$ ompi_info | grep -i ucx
Configure command line: ... '--with-ucx' ...
MCA osc: ucx (MCA v2.1.0, API v3.0.0, Component v4.1.6)
MCA pml: ucx (MCA v2.1.0, API v2.0.0, Component v4.1.6)
```

UCX also sees the Soft-RoCE device and exposes verbs transports:

```text
ubuntu@node1:~/src/osu-micro-benchmarks-7.4$ ucx_info -d | grep -E "Transport|Device|rxe|rc|ud|tcp"
# Memory domain: tcp
#      Transport: tcp
#         Device: enp1s0
#      Transport: tcp
#         Device: enp2s0
#      Transport: tcp
#         Device: lo
# Memory domain: rxe0
#      Transport: rc_verbs
#         Device: rxe0:1
#      Transport: ud_verbs
#         Device: rxe0:1
```

This proves that UCX can discover `rxe0`. The failure happens later, during MPI
endpoint setup.

## UCX / Soft-RoCE Attempt

First attempt: force OpenMPI's UCX PML over the Soft-RoCE device.

Command:

```bash
mpirun -np 2 --host node1,node2 \
  --mca pml ucx \
  -x UCX_TLS=rc,self,sm \
  -x UCX_NET_DEVICES=rxe0:1 \
  -x UCX_IB_GID_INDEX=1 \
  ~/src/osu-micro-benchmarks-7.4/c/mpi/collective/blocking/osu_allreduce
```

Observed failure:

```text
ud_ep.c:278  Fatal: UD endpoint ... unhandled timeout error
mpirun noticed that process rank 0 ... exited on signal 6 (Aborted).
```

Second attempt: force the explicit UCX verbs transport name and save the output.

Command:

```bash
mpirun -np 2 --host node1,node2 \
  --mca pml ucx \
  -x UCX_TLS=rc_verbs,self,sm \
  -x UCX_NET_DEVICES=rxe0:1 \
  -x UCX_IB_GID_INDEX=1 \
  ~/src/osu-micro-benchmarks-7.4/c/mpi/collective/blocking/osu_allreduce \
  > ~/results/osu_allreduce_ucx_rdma_attempt.txt 2>&1
```

Observed failure:

```text
UCX  ERROR   no auxiliary transport to <no debug data>: Unsupported operation
Error: ucp_ep_create(proc=0) failed: Destination is unreachable
PML add procs failed
An error occurred in MPI_Init
```

Interpretation of the failure, without analyzing benchmark values:

- UCX detects `rxe0`.
- UCX exposes `rc_verbs` and `ud_verbs` on `rxe0:1`.
- OpenMPI's UCX PML fails while creating endpoints between MPI ranks.
- The failure appears during MPI initialization or control-path setup, before a
  usable OSU allreduce result is produced.

At this stage of the investigation this looked like a hard limitation of the
virtualized Soft-RoCE + UCX setup. It did not invalidate the lower-level RDMA
validation from section A, where `rping` and `perftest` worked directly over
`rxe0`. The root cause and a working configuration were found later — see
"Root Cause Analysis" below.

## UCX Troubleshooting

The first hypothesis was that OpenMPI/UCX might be using the wrong RoCE GID
index. The GID index matters because RoCE uses GIDs to identify the RDMA address
bound to a network interface and IP address.

Command used on both nodes:

```bash
for f in /sys/class/infiniband/rxe0/ports/1/gids/*; do
  v=$(cat "$f")
  if [ "$v" != "0000:0000:0000:0000:0000:0000:0000:0000" ]; then
    i=${f##*/}
    echo "index=$i gid=$v"
    echo "  type=$(cat /sys/class/infiniband/rxe0/ports/1/gid_attrs/types/$i)"
    echo "  netdev=$(cat /sys/class/infiniband/rxe0/ports/1/gid_attrs/ndevs/$i)"
  fi
done
```

`node1` output:

```text
index=0 gid=fe80:0000:0000:0000:5054:00ff:fe95:c80e
  type=RoCE v2
  netdev=enp2s0
index=1 gid=0000:0000:0000:0000:0000:ffff:0a00:0001
  type=RoCE v2
  netdev=enp2s0
```

`node2` output:

```text
index=0 gid=fe80:0000:0000:0000:5054:00ff:fe43:3b99
  type=RoCE v2
  netdev=enp2s0
index=1 gid=0000:0000:0000:0000:0000:ffff:0a00:0002
  type=RoCE v2
  netdev=enp2s0
```

The useful GID is index `1` on both nodes:

```text
node1: ...:0a00:0001 -> 10.0.0.1
node2: ...:0a00:0002 -> 10.0.0.2
```

This confirmed that `UCX_IB_GID_INDEX=1` was the index carrying the lab's IPv4
addresses — which at the time looked like the right choice. In hindsight it was
exactly the wrong lead: the RoCEv2/IPv4 path itself turned out to be the broken
one, and the fix was to move *away* from it (see "Root Cause Analysis").

Next, UCX was retried with explicit control-plane and auxiliary transports.
The idea was to let UCX use `rc_verbs` for the RDMA path while still allowing
`ud_verbs` or `tcp` for endpoint setup.

Attempt with `UCX_NET_DEVICES=rxe0:1`:

```bash
mpirun -np 2 --host node1,node2 \
  --mca oob_tcp_if_include enp2s0 \
  --mca pml ucx \
  -x UCX_TLS=rc_verbs,ud_verbs,tcp,self,sm \
  -x UCX_NET_DEVICES=rxe0:1 \
  -x UCX_IB_GID_INDEX=1 \
  -x UCX_LOG_LEVEL=info \
  ~/src/osu-micro-benchmarks-7.4/c/mpi/collective/blocking/osu_allreduce
```

Attempt without `UCX_NET_DEVICES`, to avoid restricting the TCP auxiliary path
too aggressively:

```bash
mpirun -np 2 --host node1,node2 \
  --mca oob_tcp_if_include enp2s0 \
  --mca pml ucx \
  -x UCX_TLS=rc_verbs,ud_verbs,tcp,self,sm \
  -x UCX_IB_GID_INDEX=1 \
  -x UCX_LOG_LEVEL=info \
  ~/src/osu-micro-benchmarks-7.4/c/mpi/collective/blocking/osu_allreduce
```

Both attempts still failed with UCX aborts during MPI startup or early
collective setup. A representative failure ended with:

```text
Signal: Aborted (6)
ucs_fatal_error_format
ucp_worker_progress
mca_pml_ucx_send
MPI_Barrier
osu_allreduce
mpirun noticed that process rank 0 ... exited on signal 6 (Aborted).
```

Troubleshooting conclusion:

- The RoCEv2 GID table is correct.
- The private lab network GIDs are present on `index=1` for both nodes.
- UCX can discover `rxe0` and exposes `rc_verbs` / `ud_verbs`.
- Adding TCP as an auxiliary UCX transport did not make OpenMPI's UCX PML
  complete endpoint setup.
- The failure is isolated above the verbs layer: direct RDMA tools work, while
  OpenMPI + UCX over Soft-RoCE does not complete in this VM environment.

Layer isolation:

```text
Validated:
  rping / perftest -> verbs -> rxe0 -> enp2s0 -> 10.0.0.0/24

Validated:
  OSU / OpenMPI -> OB1 -> TCP -> enp2s0 -> 10.0.0.0/24

Failed:
  OSU / OpenMPI -> UCX PML -> UCX endpoint setup -> rxe0
```

## Root Cause Analysis

The failure was isolated layer by layer, removing one component at a time.

**Step 1: UD works at the verbs layer.** UCX wireup between workers does not use
RC; it uses UD (`ud_verbs`) as the auxiliary transport. UD was therefore tested
directly with perftest, at all message sizes up to the MTU:

```bash
# node1
ib_send_lat -c UD -d rxe0 -x 1 -a
# node2
ib_send_lat -c UD -d rxe0 -x 1 -a 10.0.0.1
```

This passes for every size from 2 to 1024 bytes (~17-21 us typical). The kernel
UD send/receive path itself is functional.

**Step 2: the failure reproduces without MPI.** `ucx_perftest` over `ud_verbs`
alone hits the exact same fatal error as the MPI runs, which exonerates OpenMPI
completely:

```bash
# node1 (server)
UCX_TLS=ud_verbs,self UCX_NET_DEVICES=rxe0:1 UCX_IB_GID_INDEX=1 ucx_perftest -t tag_lat
# node2 (client)
UCX_TLS=ud_verbs,self UCX_NET_DEVICES=rxe0:1 UCX_IB_GID_INDEX=1 ucx_perftest 10.0.0.1 -t tag_lat

ud_ep.c:278  Fatal: UD endpoint ... unhandled timeout error
```

**Step 3: the packets are on the wire and are well-formed.** `tcpdump` on UDP
port 4791 during a failing run shows both nodes sending 92-byte UCX connection
request packets, retransmitted with exponential backoff for 30 seconds. Decoding
the BTH/DETH headers shows correct destination QPNs (matching the QPNs each
side logs), the correct UCX QKey (`0x1ee7a330`), and correct worker addresses.
The packets reach the destination interface in both directions, but neither
side ever answers.

**Step 4: UCX never receives anything.** `UCX_LOG_LEVEL=debug` shows the sender
resending PSN 1 until `peer_timeout` (30 s) expires, with zero receive activity.
The packets are lost between the interface and the UD queue pair.

**Explanation.** With `UCX_IB_GID_INDEX=1` the wire format is RoCEv2 over IPv4.
In that format there is no GRH on the wire: the receiving `rxe` driver must
synthesize the GRH from the IP header before delivering the packet to a UD QP.
UCX's UD transport, unlike perftest, consumes the GRH: at startup it builds a
hash of the local GIDs (visible in the debug log as `adding gid ... to hash`)
and validates incoming packets against it. On kernel `6.8.0-124-generic`, this
RoCEv2/IPv4 UD receive path never delivers usable packets to the UCX QP, while
raw perftest UD (which ignores the GRH) works. This is why every layer looked
healthy in isolation while UCX endpoint setup could not complete.

**Confirmation.** Switching both sides to GID index 0 (the link-local GID, i.e.
RoCEv2 over IPv6, where a real IPv6 header exists on the wire and the GRH
mapping is trivial) makes the exact same UCX test pass immediately:

```bash
UCX_TLS=ud_verbs,self UCX_NET_DEVICES=rxe0:1 UCX_IB_GID_INDEX=0 ucx_perftest ... -t tag_lat
# Final: 1000 iterations, 18.3 us average latency
```

`rc_verbs` with UD wireup passes as well (20.3 us).

## Working MPI over UCX over Soft-RoCE

With the GID index 0 workaround, the originally intended path completes:

```bash
mpirun -np 2 --host node1,node2 \
  --mca pml ucx \
  --mca oob_tcp_if_include enp2s0 \
  -x UCX_TLS=rc_verbs,ud_verbs,self,sm \
  -x UCX_NET_DEVICES=rxe0:1 \
  -x UCX_IB_GID_INDEX=0 \
  ~/src/osu-micro-benchmarks-7.4/c/mpi/collective/blocking/osu_allreduce \
  > ~/results/osu_allreduce_ucx_rdma.txt 2>&1
```

Observed output (full run, 1 B to 1 MiB):

```text
# OSU MPI Allreduce Latency Test v7.4
# Datatype: MPI_CHAR.
# Size       Avg Latency(us)
1                      39.90
2                      78.73
4                      79.58
8                      40.01
...
1048576             17017.79
```

The transport list `UCX_TLS=rc_verbs,ud_verbs,self,sm` contains no TCP
transport and `UCX_NET_DEVICES` is restricted to `rxe0:1`, so the inter-node
data path is verbs over Soft-RoCE by construction:

```text
osu_allreduce
  -> OpenMPI
    -> UCX PML
      -> rc_verbs (data) / ud_verbs (wireup)
        -> rxe0
          -> enp2s0
            -> private lab network 10.0.0.0/24
```

Note for the analysis step: this run uses the IPv6 link-local GID, while the
forced-TCP baseline uses IPv4 on the same interface. Both cross the same
`enp2s0` link, so the RDMA-vs-TCP comparison remains on the same physical path.

## Current State

Working:

- OpenMPI process launch across `node1` and `node2`.
- OSU point-to-point benchmarks.
- OSU allreduce with default OpenMPI transport.
- OSU allreduce with forced TCP over `enp2s0` on the private lab network.
- UCX discovery of the `rxe0` Soft-RoCE device.
- OSU allreduce through OpenMPI's UCX PML over `rxe0`, using
  `UCX_IB_GID_INDEX=0` (RoCEv2 over IPv6 link-local).

Known limitation:

- The RoCEv2/IPv4 path (`UCX_IB_GID_INDEX=1`) fails during UCX endpoint setup
  on kernel `6.8.0-124-generic`: the `rxe` UD receive path does not deliver
  usable packets to UCX, although raw perftest UD traffic passes. A newer
  kernel (HWE) may remove the need for the workaround.

Both sides of the target comparison are now available on the same physical
path:

```text
same operation: osu_allreduce
transport A: OpenMPI -> UCX -> rc_verbs -> rxe0 -> enp2s0   (RDMA / Soft-RoCE)
transport B: OpenMPI -> OB1 -> TCP -> enp2s0                (classic TCP)
```

## Files Exported to the Host

The raw VM outputs were copied from `node1` to the repository:

```bash
cd ~/Documents/lab_hpc_networking/ai-fabric-lab
mkdir -p results/mpi
scp -i ~/.ssh/ai_fabric_lab -r ubuntu@192.168.122.38:/home/ubuntu/results/* results/mpi/
```

Current files:

```text
results/mpi/osu_allreduce_default.txt
results/mpi/osu_allreduce_tcp.txt
results/mpi/osu_allreduce_ucx_rdma_attempt.txt
results/mpi/osu_allreduce_ucx_rdma.txt
```

`osu_allreduce_ucx_rdma_attempt.txt` is kept as the record of the original
failure (RoCEv2/IPv4 GID). `osu_allreduce_ucx_rdma.txt` is the completed run
with the GID index 0 workaround.
