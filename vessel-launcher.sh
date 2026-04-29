#!/bin/bash

# Vessel Runtime Engine - Resource Allocation Wrapper
# Must be executed with root privileges (sudo)

CGROUP_NAME="vessel_sandbox"
CGROUP_ROOT="/sys/fs/cgroup"
CAGE_PATH="$CGROUP_ROOT/$CGROUP_NAME"

# Resource Limits
MAX_PIDS=50
CPU_QUOTA=100000
CPU_PERIOD=100000

echo "Initializing Vessel Resource Manager..."

# 1. State Cleanup
# If the cage already exists from a previous run, tear it down to reset metrics.
if [ -d "$CAGE_PATH" ]; then
    echo "Found existing cage. Purging old state..."
    rmdir "$CAGE_PATH" 2>/dev/null || { echo "Failed to remove old cage. Are processes still attached?"; exit 1; }
fi

# 2. Controller Verification
# Ensure the root cgroup is delegating the necessary controllers down the tree.
echo "+cpu +pids" > "$CGROUP_ROOT/cgroup.subtree_control"

# 3. Cage Instantiation
echo "Forging new cgroup hierarchy at $CAGE_PATH..."
mkdir "$CAGE_PATH"

# 4. Resource Enforcement
# Enforce the maximum thread/process count to prevent fork bombs.
echo "Applying PID limit: $MAX_PIDS"
echo "$MAX_PIDS" > "$CAGE_PATH/pids.max"

# Enforce the CPU time slice quota.
echo "Applying CPU throttle: $CPU_QUOTA / $CPU_PERIOD"
echo "$CPU_QUOTA $CPU_PERIOD" > "$CAGE_PATH/cpu.max"

# 5. Process Migration
# Attach this current bash script's PID to the cage. 
# Any command executed after this point will be born inside the constraints.
echo "Locking process $$ into the sandbox..."
echo $$ > "$CAGE_PATH/cgroup.procs"

# 6. Handover
echo "Resource limits active. Entering container namespace..."
echo "------------------------------------------------------"

exec python3 vessel.py
