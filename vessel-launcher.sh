#!/bin/bash

if [ "$EUID" -ne 0 ]; then
  echo "FATAL: Vessel requires root privileges for orchestration. Please run with sudo."
  exit 1
fi

if ! [[ ($# -eq 1 && "$1" == "shell") || ($# -eq 2 && "$1" == "sql" && "$2" -gt 0 && "$2" -le 20) ]]; then
    echo "Incorrect usage. Valid deployment targets:"
    echo "  sudo ./vessel-launcher.sh shell"
    echo "  sudo ./vessel-launcher.sh sql [1-20]"
    exit 1
fi

cleanup_rootfs() {
    local dir=$1
    if [ -d "$dir" ]; then
        grep "$dir" /proc/mounts | awk '{print $2}' | sort -r | xargs -r sudo umount -l 2>/dev/null
        sudo rm -rf "$dir"
    fi
}

echo "Validating project environment and permissions..."
chown -R "${SUDO_USER:-$USER}:${SUDO_USER:-$USER}" vessel-engine
echo "Compiling the Spring Boot sharding payload..."
cd vessel-engine || exit
sudo -u "${SUDO_USER:-$USER}" ./mvnw clean package -DskipTests
if [ $? -ne 0 ]; then
    echo "FATAL: Maven build failed. Check for file locks or syntax errors."
    exit 1
fi
cd ..

CLUSTER_ROOT="/sys/fs/cgroup/vessel_cluster"
if ! command -v python3-pymysql &> /dev/null; then
    apt install python3-pymysql -y > /dev/null 2>&1
fi

echo "Sweeping dirty network interfaces from previous sessions..."
for i in {1..20} 99; do
    ip link delete v-host$i 2>/dev/null || true
done

if ! ip link show vessel_br0 > /dev/null 2>&1; then
    echo "Provisioning global Layer 2 switch (vessel_br0)..."
    ip link add name vessel_br0 type bridge
    ip addr add 10.0.0.1/24 dev vessel_br0
    ip link set vessel_br0 up
fi

sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -P FORWARD ACCEPT

if [ -d "$CLUSTER_ROOT" ]; then
    find "$CLUSTER_ROOT"/vessel_sandbox_* -name "cgroup.kill" -exec sh -c 'echo 1 > {}' \; 2>/dev/null
fi

echo "Establishing unified cluster cgroup..."
mkdir -p "$CLUSTER_ROOT"
echo "+cpu +pids +memory" > "$CLUSTER_ROOT/cgroup.subtree_control"
echo "200000 100000" > "$CLUSTER_ROOT/cpu.max"
mkdir -p "logs"

echo "Building and Verifying the base Alpine OS Image..."
python3 provisionLinux.py

if [ "$1" == "shell" ]; then
    echo "Provisioning diagnostic Shell environment (Shard 1)..."
    cleanup_rootfs "/tmp/vessel-root_1"
    cp -a "/tmp/vessel-root-base" "/tmp/vessel-root_1"
    exec ./container-launcher.sh shell 1
else
    trap 'exec 2>/dev/null; echo "Shutting down cluster..."; trap - SIGINT SIGTERM; find /sys/fs/cgroup/vessel_cluster/vessel_sandbox_* -name "cgroup.kill" -exec sh -c "echo 1 > {}" \;; wait; echo "Cluster completely offline."; exit 0' SIGINT SIGTERM

    echo "Rapidly cloning and booting the MariaDB data tier..."
    for ((i=1; i<=$2; i++)); do
        echo "Cloning filesystem for Database Node $i..."
        cleanup_rootfs "/tmp/vessel-root_$i"
        cp -a "/tmp/vessel-root-base" "/tmp/vessel-root_$i"
        ./container-launcher.sh sql "$i" > "logs/db_node_${i}_boot.log" 2>&1 &
    done
    
    echo "Allowing database tier to initialize..."
    sleep 5
    
    echo "Provisioning Spring Boot Application Router..."
    SPRING_NODE_ID=99
    cleanup_rootfs "/tmp/vessel-root_$SPRING_NODE_ID"
    cp -a "/tmp/vessel-root-base" "/tmp/vessel-root_$SPRING_NODE_ID"

    export VESSEL_SHARD_COUNT="$2"
    
    ./container-launcher.sh spring "$SPRING_NODE_ID" "$2" > "logs/spring_router_boot.log" 2>&1 &
    
    echo "Cluster is running. Spring Boot Router is booting on 10.0.0.100."
    echo "Press CTRL+C to initiate graceful teardown."
    wait
fi