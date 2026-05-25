#!/bin/bash
MODE="$1"
SHARD_ID="$2"
SHARD_COUNT="${3:-3}"

CLUSTER_ROOT="/sys/fs/cgroup/vessel_cluster"
CAGE_PATH="$CLUSTER_ROOT/vessel_sandbox_$SHARD_ID"

if [ -d "$CAGE_PATH" ]; then
    find "$CAGE_PATH" -name "cgroup.kill" -exec sh -c 'echo 1 > {}' \; 2>/dev/null
    rmdir "$CAGE_PATH" 2>/dev/null
fi

mkdir -p "$CAGE_PATH"

echo 2000 > "$CAGE_PATH/pids.max"
echo "100000 100000" > "$CAGE_PATH/cpu.max"
echo "1000000000" > "$CAGE_PATH/memory.max"

exec python3 vessel.py "$MODE" "$SHARD_ID" "$SHARD_COUNT"