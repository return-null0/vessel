#!/bin/bash

if [ "$EUID" -ne 0 ]; then
  echo "FATAL: Vessel requires root privileges. Please run with sudo."
  exit 1
fi

if ! [[ ($# -eq 1 && "$1" == "shell") || ($# -eq 2 && "$1" == "spring" && "$2" -gt 0) ]]; then
    echo "Incorrect usage. Valid deployment targets:"
    echo "  sudo ./vessel-launcher.sh shell"
    echo "  sudo ./vessel-launcher.sh spring [1-9]"
    exit 1
fi

echo "Compiling the Spring Boot sharding payload..."
cd vessel-engine || exit
./mvnw clean package -DskipTests
cd ..

CLUSTER_ROOT="/sys/fs/cgroup/vessel_cluster"
sudo apt install python3-pymysql -y

if ! ip link show vessel_br0 > /dev/null 2>&1; then
    echo "Provisioning global Layer 2 switch (vessel_br0)..."
    ip link add name vessel_br0 type bridge
    ip addr add 10.0.0.1/24 dev vessel_br0
    ip link set vessel_br0 up
fi

if [ -d "$CLUSTER_ROOT" ]; then
    find "$CLUSTER_ROOT"/vessel_sandbox_* -name "cgroup.kill" -exec sh -c 'echo 1 > {}' \; 2>/dev/null
fi

echo "Establishing unified cluster cgroup..."
mkdir -p "$CLUSTER_ROOT"
echo "+cpu +pids +memory" > "$CLUSTER_ROOT/cgroup.subtree_control"
echo "200000 100000" > "$CLUSTER_ROOT/cpu.max"

mkdir -p "$CLUSTER_ROOT/orchestrator"
echo $$ > "$CLUSTER_ROOT/orchestrator/cgroup.procs"
mkdir -p "logs"

echo "Building/Verifying the base OS Image..."
python3 provisionLinux.py

if [ "$1" == "shell" ]; then
    echo "Provisioning diagnostic Shell environment (Shard 1)..."
    rm -rf "/tmp/vessel-root_1" 2>/dev/null
    cp -a "/tmp/vessel-root-base" "/tmp/vessel-root_1"
    exec ./container-launcher.sh shell 1
else
    trap 'exec 2>/dev/null; echo "Shutting down cluster..."; trap - SIGINT SIGTERM; find /sys/fs/cgroup/vessel_cluster/vessel_sandbox_* -name "cgroup.kill" -exec sh -c "echo 1 > {}" \;; wait; echo "Cluster completely offline."; exit 0' SIGINT SIGTERM

    echo "Rapidly cloning and booting the MariaDB data tier..."
    for ((i=1; i<=$2; i++)); do
        echo "Cloning filesystem for Database Node $i..."
        rm -rf "/tmp/vessel-root_$i" 2>/dev/null
        cp -a "/tmp/vessel-root-base" "/tmp/vessel-root_$i"
        
        ./container-launcher.sh sql "$i" > "logs/db_node_${i}_boot.log" 2>&1 &
    done
    
    echo "Provisioning Spring Boot Application Router..."
    SPRING_NODE_ID=99
    rm -rf "/tmp/vessel-root_$SPRING_NODE_ID" 2>/dev/null
    cp -a "/tmp/vessel-root-base" "/tmp/vessel-root_$SPRING_NODE_ID"
    
    ./container-launcher.sh spring "$SPRING_NODE_ID"
    
    echo "Cluster is running. Spring Boot Router is booting on 10.0.0.100."
    echo "Press CTRL+C to initiate graceful teardown."
    wait
fi