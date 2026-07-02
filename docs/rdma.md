# Soft-RoCE and RDMA Validation

This note documents the first working RDMA layer of the lab: Soft-RoCE over the
private VM network. The goal of this step is to prove that both VMs expose an
RDMA verbs device, that the two nodes can exchange RDMA traffic, and that
`perftest` produces initial latency and bandwidth numbers.

## Lab Context

The lab runs on two Ubuntu Server VMs connected through a private libvirt
network:

```text
node1: 10.0.0.1/24
node2: 10.0.0.2/24

node1 enp2s0 <---- libvirt rdma-lab bridge ----> enp2s0 node2
       rxe0                                      rxe0
```

Soft-RoCE creates an RDMA device (`rxe0`) on top of a normal Ethernet
interface (`enp2s0`). The Ethernet interface still carries packets, but
applications using verbs see an RDMA device and can create queue pairs,
registered memory regions, and RDMA operations.

## Commands Used

Soft-RoCE is loaded and attached to the private lab interface on each VM:

```bash
sudo modprobe rdma_rxe
sudo rdma link add rxe0 type rxe netdev enp2s0
rdma link show
```

The userspace RDMA tooling is installed on both nodes:

```bash
sudo apt update
sudo apt install -y rdma-core rdmacm-utils perftest ibverbs-utils
```

Package roles:

- `rdma-core`: base userspace RDMA libraries and configuration.
- `rdmacm-utils`: RDMA CM test tools, including `rping`.
- `perftest`: bandwidth and latency benchmarks such as `ib_send_lat`,
  `ib_write_bw`, and `ib_read_bw`.
- `ibverbs-utils`: verbs inspection tools such as `ibv_devices` and
  `ibv_devinfo`.

## RDMA Device Discovery

`ibv_devices` and `ibv_devinfo` confirm that the verbs stack sees `rxe0` on
`node1`.

```text
ubuntu@node1:~$ ibv_devices ; ibv_devinfo
    device                 node GUID
    ------              ----------------
    rxe0                505400fffe95c80e
hca_id: rxe0
        transport:                      InfiniBand (0)
        fw_ver:                         0.0.0
        node_guid:                      5054:00ff:fe95:c80e
        sys_image_guid:                 5054:00ff:fe95:c80e
        vendor_id:                      0xffffff
        vendor_part_id:                 0
        hw_ver:                         0x0
        phys_port_cnt:                  1
                port:   1
                        state:                  PORT_ACTIVE (4)
                        max_mtu:                4096 (5)
                        active_mtu:             1024 (3)
                        sm_lid:                 0
                        port_lid:               0
                        port_lmc:               0x00
                        link_layer:             Ethernet
```

The same check is valid on `node2`.

```text
ubuntu@node2:~$ rdma link show
link rxe0/1 state ACTIVE physical_state LINK_UP netdev enp2s0

ubuntu@node2:~$ ibv_devices ; ibv_devinfo
    device                 node GUID
    ------              ----------------
    rxe0                505400fffe433b99
hca_id: rxe0
        transport:                      InfiniBand (0)
        fw_ver:                         0.0.0
        node_guid:                      5054:00ff:fe43:3b99
        sys_image_guid:                 5054:00ff:fe43:3b99
        vendor_id:                      0xffffff
        vendor_part_id:                 0
        hw_ver:                         0x0
        phys_port_cnt:                  1
                port:   1
                        state:                  PORT_ACTIVE (4)
                        max_mtu:                4096 (5)
                        active_mtu:             1024 (3)
                        sm_lid:                 0
                        port_lid:               0
                        port_lmc:               0x00
                        link_layer:             Ethernet
```

Analysis:

- `rxe0` is visible to libibverbs, so userspace RDMA applications can open the
  device.
- `state: PORT_ACTIVE` means the RDMA port is usable.
- `link_layer: Ethernet` confirms this is RoCE/Soft-RoCE behavior, not a
  physical InfiniBand fabric.
- `active_mtu: 1024` is the MTU actually used by the RDMA port in these tests.
- LID values are `0` because this is Ethernet/RoCE, not an InfiniBand subnet
  managed by a subnet manager.

## RDMA Connectivity With rping

`rping` validates RDMA connection management and traffic exchange.

Server on `node1`:

```bash
rping -s -v
```

Client on `node2`:

```bash
rping -c -a 10.0.0.1 -v
```

Observed server-side output:

```text
server ping data: rdma-ping-19781: DEFGHIJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopq
server ping data: rdma-ping-19782: EFGHIJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqr
server ping data: rdma-ping-19783: FGHIJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrs
server ping data: rdma-ping-19784: GHIJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrst
server ping data: rdma-ping-19785: HIJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstu
server ping data: rdma-ping-19786: IJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuv
server ping data: rdma-ping-19787: JKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvw
server ping data: rdma-ping-19788: KLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwx
server ping data: rdma-ping-19789: LMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxy
server ping data: rdma-ping-19790: MNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyz
server ping data: rdma-ping-19791: NOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyzA
server ping data: rdma-ping-19792: OPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyzAB
server ping data: rdma-ping-19793: PQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyzABC
server ping data: rdma-ping-19794: QRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyzABCD
server ping data: rdma-ping-19795: RSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyzABCDE
server ping data: rdma-ping-19796: STUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyzABCDEF
server ping data: rdma-ping-19797: TUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyzABCDEFG
server ping data: rdma-ping-19798: UVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyzABCDEFGH
server DISCONNECT EVENT...
wait for RDMA_WRITE_ADV state 10
ubuntu@node1:~$
```

Analysis:

- The repeated `server ping data` lines prove that the two VMs exchange RDMA CM
  traffic successfully.
- The test targets `10.0.0.1`, so the RDMA path uses the private lab network,
  not the NAT management interface.
- The disconnect event appears after the client stops and is expected.

## Perftest Results

The following tests were launched with the server command on `node1` and the
client command on `node2`.

### Send Latency

Server:

```bash
ib_send_lat
```

Client:

```bash
ib_send_lat 10.0.0.1
```

Result:

```text
---------------------------------------------------------------------------------------
                    Send Latency Test
 Dual-port       : OFF          Device         : rxe0
 Number of qps   : 1            Transport type : IB
 Connection type : RC           Using SRQ      : OFF
 PCIe relax order: ON
 ibv_wr* API     : OFF
 TX depth        : 1
 Mtu             : 1024[B]
 Link type       : Ethernet
 GID index       : 1
 Max inline data : 0[B]
 rdma_cm QPs     : OFF
 Data ex. method : Ethernet
---------------------------------------------------------------------------------------
 local address: LID 0000 QPN 0x0012 PSN 0xa66708
 GID: 00:00:00:00:00:00:00:00:00:00:255:255:10:00:00:02
 remote address: LID 0000 QPN 0x0012 PSN 0xd9ad28
 GID: 00:00:00:00:00:00:00:00:00:00:255:255:10:00:00:01
---------------------------------------------------------------------------------------
 #bytes #iterations    t_min[usec]    t_max[usec]  t_typical[usec]    t_avg[usec]    t_stdev[usec]   99% percentile[usec]   99.9% percentile[usec]
 2       1000          16.55          59.50        21.27               21.69            2.18    31.37            59.50
---------------------------------------------------------------------------------------
```

Analysis:

- Message size: `2` bytes.
- Transport: RC queue pair over Soft-RoCE (`Connection type: RC`,
  `Link type: Ethernet`).
- Average latency is about `21.69 us`, with a typical value of `21.27 us`.
- The GIDs embed the IPv4 addresses:
  - `...:10:00:00:01` is `10.0.0.1`.
  - `...:10:00:00:02` is `10.0.0.2`.

### RDMA Write Bandwidth

Server:

```bash
ib_write_bw
```

Client:

```bash
ib_write_bw 10.0.0.1
```

Result:

```text
---------------------------------------------------------------------------------------
                    RDMA_Write BW Test
 Dual-port       : OFF          Device         : rxe0
 Number of qps   : 1            Transport type : IB
 Connection type : RC           Using SRQ      : OFF
 PCIe relax order: ON
 ibv_wr* API     : OFF
 TX depth        : 128
 CQ Moderation   : 1
 Mtu             : 1024[B]
 Link type       : Ethernet
 GID index       : 1
 Max inline data : 0[B]
 rdma_cm QPs     : OFF
 Data ex. method : Ethernet
---------------------------------------------------------------------------------------
 local address: LID 0000 QPN 0x0013 PSN 0x4b46fa RKey 0x00077f VAddr 0x0070be52d23000
 GID: 00:00:00:00:00:00:00:00:00:00:255:255:10:00:00:02
 remote address: LID 0000 QPN 0x0013 PSN 0x7299e0 RKey 0x0006c7 VAddr 0x007f99c0bef000
 GID: 00:00:00:00:00:00:00:00:00:00:255:255:10:00:00:01
---------------------------------------------------------------------------------------
 #bytes     #iterations    BW peak[MB/sec]    BW average[MB/sec]   MsgRate[Mpps]
 65536      5000             103.71             90.04              0.001441
---------------------------------------------------------------------------------------
```

Analysis:

- Message size: `65536` bytes, or 64 KiB.
- Average bandwidth: `90.04 MB/s`, approximately `0.72 Gb/s`.
- Peak bandwidth: `103.71 MB/s`, approximately `0.83 Gb/s`.
- This is a one-sided RDMA WRITE test: the initiator writes directly into a
  registered remote memory region.

### RDMA Read Bandwidth

Server:

```bash
ib_read_bw
```

Client:

```bash
ib_read_bw 10.0.0.1
```

Result:

```text
---------------------------------------------------------------------------------------
Device not recognized to implement inline feature. Disabling it
---------------------------------------------------------------------------------------
                    RDMA_Read BW Test
 Dual-port       : OFF          Device         : rxe0
 Number of qps   : 1            Transport type : IB
 Connection type : RC           Using SRQ      : OFF
 PCIe relax order: ON
 ibv_wr* API     : OFF
 TX depth        : 128
 CQ Moderation   : 1
 Mtu             : 1024[B]
 Link type       : Ethernet
 GID index       : 1
 Outstand reads  : 128
 rdma_cm QPs     : OFF
 Data ex. method : Ethernet
---------------------------------------------------------------------------------------
 local address: LID 0000 QPN 0x0014 PSN 0x714437 OUT 0x80 RKey 0x0008d8 VAddr 0x007a314685d000
 GID: 00:00:00:00:00:00:00:00:00:00:255:255:10:00:00:02
 remote address: LID 0000 QPN 0x0014 PSN 0x161448 OUT 0x80 RKey 0x000722 VAddr 0x007d2d2bab0000
 GID: 00:00:00:00:00:00:00:00:00:00:255:255:10:00:00:01
---------------------------------------------------------------------------------------
 #bytes     #iterations    BW peak[MB/sec]    BW average[MB/sec]   MsgRate[Mpps]
 65536      1000             132.59             131.92             0.002111
---------------------------------------------------------------------------------------
```

Analysis:

- Message size: `65536` bytes, or 64 KiB.
- Average bandwidth: `131.92 MB/s`, approximately `1.06 Gb/s`.
- Peak bandwidth: `132.59 MB/s`, approximately `1.06 Gb/s`.
- This is a one-sided RDMA READ test: the initiator reads from a registered
  remote memory region.
- The inline warning is not fatal. The test disables that feature and continues.

## Interpretation

This validates the minimum RDMA layer required for the rest of the lab:

- Both nodes expose an RDMA verbs device named `rxe0`.
- The RDMA port is active on both sides.
- RDMA traffic uses the private `10.0.0.0/24` network.
- `rping` confirms RDMA CM connectivity.
- `perftest` provides first baseline numbers for latency and one-sided
  bandwidth.

The numbers are not expected to match physical RDMA NIC performance. Soft-RoCE
runs in software on virtualized Ethernet, so CPU scheduling, VM overhead, MTU,
and the host bridge all influence the result. For this project, the important
point is that the RDMA path is functional and measurable before moving to MPI
and comparing collectives over RDMA versus TCP.

## Summary Table

| Check | Command | Node / Direction | Message size | Transport | Result | Status |
| --- | --- | --- | ---: | --- | ---: | --- |
| RDMA device visible | `ibv_devices` | node1 | N/A | Soft-RoCE | `rxe0` | OK |
| RDMA port active | `ibv_devinfo` | node1 | N/A | Ethernet / RoCE | `PORT_ACTIVE`, MTU 1024 | OK |
| RDMA device visible | `ibv_devices` | node2 | N/A | Soft-RoCE | `rxe0` | OK |
| RDMA port active | `ibv_devinfo` | node2 | N/A | Ethernet / RoCE | `PORT_ACTIVE`, MTU 1024 | OK |
| RDMA connectivity | `rping` | node2 -> node1 | rping payload | RDMA CM | ping data received | OK |
| Send latency | `ib_send_lat 10.0.0.1` | node2 -> node1 | 2 B | RC / Soft-RoCE | 21.69 us avg | OK |
| RDMA WRITE bandwidth | `ib_write_bw 10.0.0.1` | node2 -> node1 | 64 KiB | RC / Soft-RoCE | 90.04 MB/s, about 0.72 Gb/s avg | OK |
| RDMA READ bandwidth | `ib_read_bw 10.0.0.1` | node2 -> node1 | 64 KiB | RC / Soft-RoCE | 131.92 MB/s, about 1.06 Gb/s avg | OK |
