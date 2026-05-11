#!/bin/bash

MODE="$1"
SHARD_ID="$2"

# Use the nested path instead of a flat name
CLUSTER_ROOT="/sys/fs/cgroup/vessel_cluster"
CAGE_PATH="$CLUSTER_ROOT/vessel_sandbox_$SHARD_ID"

# 1. State Cleanup (Recursive kill ensures this rmdir works)
if [ -d "$CAGE_PATH" ]; then
    rmdir "$CAGE_PATH" 2>/dev/null || { echo "Cage busy. Check for orphans."; exit 1; }
fi


mkdir -p "$CAGE_PATH"

echo 50 > "$CAGE_PATH/pids.max"
echo "100000 100000" > "$CAGE_PATH/cpu.max"

# Process Migration
echo $$ > "$CAGE_PATH/cgroup.procs"

exec python3 vessel.py "$MODE" "$SHARD_ID"
