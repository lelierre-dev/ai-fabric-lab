# VM Setup Report

This report documents the initial two-node lab setup used for the Soft-RoCE/RDMA experiments.

## Goal

Build two independent Ubuntu Server VMs with:

- separate kernels, so each node can load `rdma_rxe`;
- a private lab network for RDMA traffic;
- static lab IPs: `node1=10.0.0.1`, `node2=10.0.0.2`;
- passwordless SSH for MPI and Ansible;
- a reproducible libvirt/cloud-init setup.

## Architecture

```text
                      Host: neon
                 Ubuntu 26.04 + KVM/libvirt

          NAT network: default           Private lab network: rdma-lab
          192.168.122.0/24               10.0.0.0/24
                  |                              |
        +---------+---------+          +---------+---------+
        |                   |          |                   |
    enp1s0              enp1s0      enp2s0              enp2s0
  192.168.122.38      192.168.122.x 10.0.0.1           10.0.0.2
    node1               node2        node1              node2
        |                   |          |                   |
        +-------------------+          +-------------------+
             SSH/admin path              RDMA lab fabric
```

`enp1s0` is used for host-to-VM SSH and package installation through libvirt NAT.
`enp2s0` is the isolated RDMA lab interface and is the interface used by Soft-RoCE.

## Repository Files

The source files kept in git are:

```text
VMs/
├── rdma-lab.xml
├── user-data-node1.yml
└── user-data-node2.yml
```


The active libvirt disk files live outside the repo:

```text
/var/lib/libvirt/images/ai-fabric-lab/
```

## Host Setup

The first install command had to be adapted because, on the host Ubuntu release, `qemu-kvm` is only a virtual package.

```bash
sudo apt update
sudo apt install -y qemu-system-x86 libvirt-daemon-system libvirt-clients virt-manager cloud-image-utils
sudo usermod -aG libvirt,kvm "$USER"
newgrp libvirt
```

Proof that libvirt was reachable:

```text
yohan@neon:~/Documents/lab_hpc_networking/ai-fabric-lab$ virsh list --all
 Id   Name   State
--------------------
```

At that point the empty list was expected: libvirt was working, but no VMs had been created yet.

Available storage before creating the VMs:

```text
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p5  140G   60G   73G  46% /home/yohan/Documents/lab_hpc_networking/ai-fabric-lab
```

## Private Libvirt Network

The private network is defined in `VMs/rdma-lab.xml`:

```xml
<network>
  <name>rdma-lab</name>
  <bridge name="virbr-rdma" stp="on" delay="0"/>
</network>
```

Commands:

```bash
virsh net-define VMs/rdma-lab.xml
virsh net-start rdma-lab
virsh net-autostart rdma-lab
virsh net-list --all
```

This creates an isolated libvirt bridge. It is not bridged to the physical LAN, which keeps the RDMA lab fabric contained and reproducible.

## Cloud-Init Inputs

Each VM uses a cloud-init user-data file with:

- hostname: `node1` or `node2`;
- user: `ubuntu`;
- passwordless sudo;
- SSH public key for host access;
- `/etc/hosts` entries for `node1` and `node2`.

Relevant host entries deployed into both VMs:

```text
10.0.0.1 node1
10.0.0.2 node2
```

Seed ISO generation:

```bash
cloud-localds seed-node1.iso user-data-node1.yml
cloud-localds seed-node2.iso user-data-node2.yml
```

## VM Storage Location

Creating the VMs directly from files under `/home/yohan/...` failed because the libvirt QEMU user could not traverse the home directory:

```text
ERROR    Cannot access storage file '/home/yohan/Documents/lab_hpc_networking/ai-fabric-lab/VMs/node1.qcow2' (as uid:64055, gid:992): Permission denied
```

The fix was to move generated VM artifacts under libvirt's storage path:

```bash
sudo mkdir -p /var/lib/libvirt/images/ai-fabric-lab
sudo cp noble-server-cloudimg-amd64.img seed-node1.iso seed-node2.iso /var/lib/libvirt/images/ai-fabric-lab/
```

VM disks were then created there:

```bash
sudo qemu-img create -f qcow2 -F qcow2 \
  -b /var/lib/libvirt/images/ai-fabric-lab/noble-server-cloudimg-amd64.img \
  /var/lib/libvirt/images/ai-fabric-lab/node1.qcow2 20G

sudo qemu-img create -f qcow2 -F qcow2 \
  -b /var/lib/libvirt/images/ai-fabric-lab/noble-server-cloudimg-amd64.img \
  /var/lib/libvirt/images/ai-fabric-lab/node2.qcow2 20G
```

## VM Creation

`node1`:

```bash
sudo virt-install \
  --name node1 \
  --memory 4096 \
  --vcpus 2 \
  --disk path=/var/lib/libvirt/images/ai-fabric-lab/node1.qcow2,format=qcow2 \
  --disk path=/var/lib/libvirt/images/ai-fabric-lab/seed-node1.iso,device=cdrom \
  --os-variant ubuntu24.04 \
  --network network=default \
  --network network=rdma-lab,model=virtio \
  --graphics none \
  --import
```

`node2`:

```bash
sudo virt-install \
  --name node2 \
  --memory 4096 \
  --vcpus 2 \
  --disk path=/var/lib/libvirt/images/ai-fabric-lab/node2.qcow2,format=qcow2 \
  --disk path=/var/lib/libvirt/images/ai-fabric-lab/seed-node2.iso,device=cdrom \
  --os-variant ubuntu24.04 \
  --network network=default \
  --network network=rdma-lab,model=virtio \
  --graphics none \
  --import
```

Console escape note:

```text
virsh console escape sequence: Ctrl + ]
```

On a Mac keyboard, using SSH from the host is usually easier than staying in the serial console.

## Lab Network Configuration

On `node1`, the two interfaces were detected as:

```text
ubuntu@node1:~$ ip -br addr
lo               UNKNOWN        127.0.0.1/8 ::1/128
enp1s0           UP             192.168.122.38/24 metric 100 fe80::5054:ff:fef2:3366/64
enp2s0           DOWN
```

`enp1s0` is the libvirt NAT interface.
`enp2s0` is the private `rdma-lab` interface.

Netplan for `node1`:

```yaml
network:
  version: 2
  ethernets:
    enp2s0:
      dhcp4: no
      addresses:
        - 10.0.0.1/24
```

Netplan for `node2`:

```yaml
network:
  version: 2
  ethernets:
    enp2s0:
      dhcp4: no
      addresses:
        - 10.0.0.2/24
```

After applying the `node1` config:

```text
ubuntu@node1:~$ ip -br addr show enp2s0
enp2s0           UP             10.0.0.1/24 fe80::5054:ff:fe95:c80e/64
```

## SSH

The Ubuntu cloud image does not provide a console password for the `ubuntu` user by default. Access is done with SSH keys.

From the host:

```bash
ssh -i ~/.ssh/ai_fabric_lab ubuntu@192.168.122.38
ssh -i ~/.ssh/ai_fabric_lab ubuntu@192.168.122.47
```

Important: do not use `sudo ssh` for this path, because that makes SSH use root's keys instead of the user's keys.

An SSH agent can be started with:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/ai_fabric_lab
```

For MPI, each node also needs passwordless SSH to the other node. A node-local key can be created with:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
```

Because the VMs do not allow password login, the first key exchange can be bootstrapped through the host, which already has key access to both nodes.

## Soft-RoCE Bring-Up

The first attempt to create the RXE device failed:

```text
ubuntu@node1:~$ sudo rdma link add rxe0 type rxe netdev enp2s0
error: Invalid argument
```

The interface was already up, so the next check was the kernel module:

```text
ubuntu@node1:~$ sudo modprobe rdma_rxe
modprobe: FATAL: Module rdma_rxe not found in directory /lib/modules/6.8.0-124-generic
```

On Ubuntu cloud images, `rdma_rxe` may live in the extra kernel modules package:

```bash
sudo apt update
sudo apt install -y linux-modules-extra-$(uname -r)
```

After installing the package:

```text
ubuntu@node1:~$ sudo modprobe rdma_rxe
ubuntu@node1:~$ lsmod | grep rdma_rxe
rdma_rxe              192512  0
ib_uverbs             184320  1 rdma_rxe
ip6_udp_tunnel         16384  1 rdma_rxe
udp_tunnel             32768  1 rdma_rxe
ib_core               507904  2 rdma_rxe,ib_uverbs
```

RXE device creation on the lab interface:

```text
ubuntu@node1:~$ sudo rdma link add rxe0 type rxe netdev enp2s0
ubuntu@node1:~$ rdma link show
link rxe0/1 state ACTIVE physical_state LINK_UP netdev enp2s0
```

This proves that Soft-RoCE is active on `node1`. The same setup should be applied on `node2`.

## Current Setup Status

- Host KVM/libvirt is working.
- Private libvirt network `rdma-lab` is defined.
- `node1` and `node2` were created as independent VMs.
- `node1` has `enp2s0` configured as `10.0.0.1/24`.
- Soft-RoCE is active on `node1` as `rxe0`.
- VM source inputs are kept in git.
- Generated VM disks/images are kept outside the repo and ignored by git.

## Next Validation Commands

Run these on both nodes:

```bash
ip -br addr
ping -c 3 node1
ping -c 3 node2
sudo modprobe rdma_rxe
sudo rdma link add rxe0 type rxe netdev enp2s0
rdma link show
ibv_devices
ibv_devinfo
```

Then test RDMA connectivity:

```bash
# node1
rping -s -v

# node2
rping -c -a 10.0.0.1 -v
```
