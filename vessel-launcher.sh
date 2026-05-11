#!/bin/bash

CLUSTER_ROOT="/sys/fs/cgroup/vessel_cluster"

if [[ "$#" -eq 1 && "$1" == "shell" ]]; then
    exec ./container-launcher.sh shell 1
elif [[ "$#" -eq 2 && "$1" == "sql" && "$2" -gt 0 && "$2" -lt 10 ]]; then

    if [ -d "$CLUSTER_CGROUP" ]; then
        find "$CLUSTER_CGROUP"/vessel_sandbox_* -name "cgroup.kill" -exec sh -c 'echo 1 > {}' \; 2>/dev/null
    fi
    echo "Establishing unified cluster cgroup..."
    sudo mkdir -p "$CLUSTER_ROOT"
    
    sudo sh -c "echo '+cpu +pids +memory' > $CLUSTER_ROOT/cgroup.subtree_control"
    
    # Global Cluster Limit (Example: 2 CPUs total for ALL shards)
    sudo sh -c "echo '200000 100000' > $CLUSTER_ROOT/cpu.max"
    
    #  keep the 'vessel_cluster' folder empty of processes so children can exist
    sudo mkdir -p "$CLUSTER_ROOT/orchestrator"
    sudo sh -c "echo $$ > $CLUSTER_ROOT/orchestrator/cgroup.procs"

    echo "Building the base Image..."
    python3 provisionLinux.py
    # Provision Layer 2 Virtual Switch
    ip link add name vessel_br0 type bridge 2>/dev/null
    ip addr add 10.0.0.1/24 dev vessel_br0 2>/dev/null
    ip link set vessel_br0 up

    # Signal Trap for Recursive Kill
    trap 'echo "Shutting down cluster..."; trap - SIGINT SIGTERM; find /sys/fs/cgroup/vessel_cluster/vessel_sandbox_* -name "cgroup.kill" -exec sh -c "echo 1 > {}" 2>/dev/null \;; wait 2>/dev/null; echo "Cluster completely offline."; exit 0' SIGINT SIGTERM

    echo "Rapidly cloning and booting the cluster..."
    for ((i=1; i<=$2; i++)); do
        echo "Cloning filesystem for Shard $i..."
        rm -rf "/tmp/vessel-root_$i" 2>/dev/null
        cp -a "/tmp/vessel-root-base" "/tmp/vessel-root_$i"
        ./container-launcher.sh sql "$i" > "shard_${i}_boot.log" 2>&1 &
    done
    echo "Cluster is running. Press CTRL+C to initiate graceful teardown."
    wait
else
    echo "incorrect usage"
    exit 1
fi
