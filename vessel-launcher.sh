#!/bin/bash

if [[ "$#" -eq 1 && "$1" == "shell" ]]; then
    exec ./container-launcher.sh shell 1
elif [[ "$#" -eq 2 && "$1" == "sql" && "$2" -gt 0 && "$2" -lt 10 ]]; then

    echo "Establishing unified cluster cgroup..."
    CLUSTER_CGROUP="/sys/fs/cgroup/vessel_cluster"
    
    mkdir -p "$CLUSTER_CGROUP"
    echo "200000 100000" > "$CLUSTER_CGROUP/cpu.max"
    echo "2G" > "$CLUSTER_CGROUP/memory.max"
    echo "+cpu +memory +pids" > "$CLUSTER_CGROUP/cgroup.subtree_control"
    echo $$ > "$CLUSTER_CGROUP/cgroup.procs"
    
    echo "Building the base Image..."
    python3 provisionLinux.py

    # Establish the signal relay
    trap 'echo "Interrupt caught. Broadcasting shutdown signal to cluster..."; kill -SIGINT $(jobs -p) 2>/dev/null; wait; echo "Cluster completely offline."; exit 0' SIGINT SIGTERM

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
