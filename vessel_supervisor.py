#!/bin/bash
if [ "$EUID" -ne 0 ]; then
  echo "FATAL: Vessel requires root privileges."
  exit 1
fi

if ! command -v ip &> /dev/null; then echo "Missing iproute2. Install it."; exit 1; fi

CLUSTER_ROOT="/sys/fs/cgroup/vessel_cluster"

echo "Sweeping dirty network interfaces..."
for i in {1..20} 99; do /sbin/ip link delete v-host$i 2>/dev/null || true; done

if ! /sbin/ip link show vessel_br0 > /dev/null 2>&1; then
    /sbin/ip link add name vessel_br0 type bridge
    /sbin/ip link set vessel_br0 up
fi

/sbin/sysctl -w net.ipv4.ip_forward=1 > /dev/null

mkdir -p "$CLUSTER_ROOT"
echo "+cpu +pids +memory" > "$CLUSTER_ROOT/cgroup.subtree_control" 2>/dev/null

echo "Building and Verifying base OS..."
python3 provisionLinux.py

if [ "$1" == "shell" ]; then
    rm -rf "/tmp/vessel-root_1"
    cp -a "/tmp/vessel-root-base" "/tmp/vessel-root_1"
    exec ./container-launcher.sh shell 1
else
    trap 'echo "Shutting down cluster..."; find /sys/fs/cgroup/vessel_cluster/vessel_sandbox_* -name "cgroup.kill" -exec sh -c "echo 1 > {}" \;; exit 0' SIGINT SIGTERM
    for ((i=1; i<=$2; i++)); do
        rm -rf "/tmp/vessel-root_$i"
        cp -a "/tmp/vessel-root-base" "/tmp/vessel-root_$i"
        ./container-launcher.sh sql "$i" &
    done
    sleep 5
    rm -rf "/tmp/vessel-root_99"
    cp -a "/tmp/vessel-root-base" "/tmp/vessel-root_99"
    ./container-launcher.sh spring 99 "$2" &
    wait
fi