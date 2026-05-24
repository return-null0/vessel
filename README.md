# Vessel: A Bare-Metal Linux Container Engine

Vessel is a high-performance, lightweight container runtime engineered from the ground up using raw Linux system calls. By bypassing high-level abstractions like Docker, Vessel interfaces directly with the kernel to provide isolated execution environments. It is designed for developers who require granular control over system processes, filesystem isolation, and horizontal database scaling.

## Technical Architecture Overview

Vessel operates at the intersection of process orchestration and kernel-level resource management. The engine leverages the Linux kernel's most robust security and isolation primitives.

## Kernel-Level Isolations (The "Vessel Boundary")
**Vessel constructs an impenetrable cage for each shard using:**

| Primitive| Purpose |
| -------- | -------- | 
| PID Namespace| Ensures the containerized database operates as PID 1, unaware of host processes. | 
| Mount Namespace | Provides a private filesystem view via Alpine Linux rootfs, preventing access to the host host OS. |
| Network Namespace | Creates a virtualized network stack, isolating the container's ports from the host network.|
| Cgroup v2 | Enforces hard limits on CPU time slices and memory consumption, preventing resource starvation.|
| veth Pairs/Bridge | Connects isolated namespaces via a software bridge to the host's 10.0.0.0/24 subnet.|
| PTY Virtualization | Bridges master/slave pseudoterminals to provide interactive shell support without leaking state to `/dev` |

----

## The Control Plane: Spring Boot Integration
The orchestration layer is augmented by a Spring Boot-based Control Plane. This backend service serves the interactive Dashboard and acts as a resilient proxy for all database sharding operations.

- Serving the UI: The DashboardController serves the interactive HTML interface, providing real-time cluster visualization.

- Proxy Logic: By abstracting the JDBC connections, the Spring engine allows for unified data aggregation (the "Unshard" functionality) across independently sharded MariaDB instances.

- Resilience: The backend implements auto-healing JdbcTemplate caches, which dynamically discard dead connections to terminated containers and recreate them upon node recovery.

## Component Deep Dive

The execution phase begins by establishing a unified hardware sanctuary for the entire architecture. Before any individual shard boots, the orchestrator script constructs a master cluster within the Cgroup v2 hierarchy and enables subtree delegation.

Key Detail: By locking the main deployment loop into the parent cgroup, every spawned sandbox inherits absolute CPU and memory limits. This kernel-level kill switch allows the host to cleanly terminate the entire database cluster simultaneously without leaving rogue orphan processes.

Scaling from a single container to a sharded cluster requires a robust routing topology. Vessel abandons simple crossover cables for a centralized software bridge operating natively at Layer 2.

**Key Detail**: The virtual switch architecture assigns the primary gateway directly to the bridge interface. This ensures all database shards reside on the same `10.0.0.0/24` subnet, enabling native cross-container communication and frictionless proxy routing.

The system uses a precise sequence of isolated cloning to cross the namespace boundary without collapsing host orchestration.


1. Host Manager: Root execution, provisions the cgroup cage.

2. Bridge: Spawned via first `fork()`, executes unshare to carve out namespaces.

3. PID 1 Supervisor: Spawned via second `fork()`, configures internal IP and mounts proc.

4. The Payload: Spawned via final `execvp()`, runs the target MariaDB binary with dropped privileges.

The Node Health Dashboard aggregates live hardware metrics from isolated Cgroup v2 filesystems.

**Key Detail**: A native POSIX thread sits in a zero-CPU wait state inside the container's PID 1 namespace. When the host issues a `SIGUSR1` interrupt, this thread reads kernel cgroup data, ensuring observability without impacting database performance.

# Deployment and Configuration

## Prerequisites

- Operating System: Native Linux (Kernel 5.x+).

- Dependencies: `Python3`, `pymysql`, `OpenJDK 21`.

- Privileges: Absolute root (`sudo`) is required for namespace and cgroup manipulation.


# Quick Start

1. Prepare Environment: Clone the repository and ensure your JDK 21 path is available.

2. Build Backend: Use the provided Maven wrapper to compile the management engine:
    
    `
    ./mvnw clean package -DskipTests`

    `cp vessel-engine/target/vessel-engine-0.0.1-SNAPSHOT.jar /app/vessel-engine.jar 
`

3. Configure Startup: Vessel uses `vessel.py` to launch shards. Ensure your startup script uses `shutil.which("java")` for dynamic path resolution to prevent `FileNotFoundError`.

4. Ensure your `VesselEngineApplication` includes 
`@SpringBootApplication(exclude = {DataSourceAutoConfiguration.class})`
to prevent conflict with the `DashboardController`.

## Running the Engine

- Interactive Mode: `sudo ./vessel-launcher.sh shell`

- Production SQL Mode: `sudo ./vessel-launcher.sh sql [shardCount]`


| Endpoint | Method | Description |
| -------- | -------- | -------- | 
| `/api/cluster-state` | GET | Returns telemetry, record count, and health status for all shards.| 
| `/api/unshard` | GET | Aggregates data from all shards into a single unified SQL view. |
| /api/kill | POST | Triggers `SIGKILL` on target shard (requires confirmation).| 
| `/api/restart` | POST | Gracefully restarts the database payload on the target shard. |



## Troubleshooting Guide
- **"No database selected"** errors: Ensure your queries use fully qualified table names (e.g., `appdata.cluster_data`). The engine is designed to lazily initialize the schema, so this ensures operations succeed regardless of session state.

- **Startup Hangs** : The engine uses a dynamic `java_bin` path lookup. If the system cannot find Java, verify the `JAVA_HOME` environment variable inside your launch script.

**Dashboard Stale Data** : The dashboard utilizes a cache-busting timestamp (`?t=Date.now()`) in the fetch API. If you see stale status (Red/Orange), check the `DashboardController` logs for `JdbcTemplate` initialization failures.