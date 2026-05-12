# Vessel
A minimal Linux container engine designed to demonstrate the fundamentals of OS-level virtualization.
<details>
<summary><b>View Photo 1: Unified Cluster Orchestration & Resource Caging</b></summary>

<img src="pics/pic1.png" width="800px">

The execution phase begins by establishing a unified hardware sanctuary for the entire architecture. Before any individual shard boots, the orchestrator script constructs a master cluster within the Cgroup v2 hierarchy and enables subtree delegation.

**Key Detail:** By locking the main deployment loop into the parent cgroup, every spawned sandbox inherits absolute CPU and memory limits. This architectural choice inherently creates a kernel-level kill switch, allowing the host to cleanly terminate the entire database cluster simultaneously without leaving rogue orphan processes.
</details>

<details>
<summary><b>View Photo 2: Layer 2 Routing & Subnet Interconnection</b></summary>

<img src="pics/pic2.png" width="800px">

Scaling from a single container to a sharded cluster requires a robust routing topology. Vessel abandons simple crossover cables for a centralized software bridge operating natively at Layer 2.

**Key Detail:** The virtual switch architecture strips IP addresses from the host-side cables and assigns the primary gateway directly to the bridge interface. This ensures all database shards reside cleanly on the same 10.0.0.0/24 subnet, enabling native cross-container communication and frictionless proxy routing without host-level firewall collisions.
</details>

<details>
<summary><b>View Photo 3: The Triple-Fork Architecture in Action</b></summary>

<img src="pics/pic3.png" width="800px">

Inspecting the kernel's process tree reveals the exact anatomical structure of OS-level virtualization. The visual indentation perfectly maps the namespace isolation strategy.

**Key Detail:** You can visually trace the execution boundary. The Python Host Manager and Bridge process remain permanently anchored to the host, while the Supervisor safely crosses the void to become PID 1 inside the sandbox. The status flags further confirm that background telemetry threads are actively operating alongside the database daemon within the identical isolated memory space.
</details>


## Overview
Vessel bypasses high-level abstractions like Docker or containerd to interface directly with the Linux kernel. It constructs isolated environments using raw system calls, kernel namespaces, control groups, and an automated Layer 2 virtual switch. This project serves as a bare-metal implementation of a container runtime, proving that containers are simply a specific configuration of native Linux security features and routing tables rather than standalone virtual machines.
The engine is designed with a dual-mode architecture. You can seamlessly transition between an interactive learning environment in shell mode, or deploy a headless, production-grade sharded database cluster in SQL mode. In this sharded SQL deployment, the orchestration script scales horizontally; every individual container strictly executes its own independent triple-fork sequence, drops root privileges, and spawns internal telemetry threads. Despite this aggressive process isolation, all the resulting database sandboxes remain seamlessly interconnected to one another and back to the host via the unified virtual network bridge.


### The Process Tree: Clarifying the Container Anatomy
It is a common misconception that the Bridge and the Supervisor are the exact same entity. In reality, the system uses a precise sequence of isolated cloning to cross the namespace boundary without collapsing the host orchestration. The Bridge acts as the structural host anchor, while the Supervisor serves as the internal administrator.


| Process Role | Execution Location | Responsibility|
| -------- | -------- | -------- |
| Host Manager| Host Machine | The root execution. Provisions the unified cgroup cage, assigns network cables to the virtual switch, and monitors the container from the outside.| 
| Bridge | Host Machine | Spawned via the first os.fork(). Executes the unshare command to carve out the namespaces, but remains permanently stuck on the host side to prevent the kernel from garbage-collecting the newly forged environments.|
| PID 1 Supervisor | Isolated Sandbox | Spawned via the second os.fork(). Birthed directly across the boundary into the isolated namespaces. It configures the internal IP, mounts the pseudo-filesystems (/proc), and runs the telemetry threads.|
| The Payload | Isolated Sandbox | Spawned via the final os.fork() and replaced using os.execvp. The actual target application (MariaDB or an Alpine shell). Drops root privileges to run securely within the enforced constraints.|
## Core Architecture and Execution Flow
The engine relies on a physically separated architecture, utilizing distinct Linux kernel mechanisms spread across four primary components to establish an impenetrable container boundary with real-time telemetry and basic network access.

1. **Build-Phase Software Injection (provisionLinux.py)**
This script acts as the infrastructure compiler. It provisions an Alpine Linux Mini Root Filesystem, dynamically mirrors the host machine's DNS routing configuration, and handles the compilation and injection of external software directly into the static filesystem image before runtime isolation occurs.

2. **Resource Caging & Initialization (vessel-launcher.sh)**
This shell script serves as the resource manager and execution entry point. It interfaces directly with the host kernel's Cgroup v2 pseudo-filesystem to construct the sandbox environment. It performs legacy state cleanup, applies strict hardware ceilings for CPU time slices, and securely locks its own process into the cgroup tree before handing execution over to the Python engine.

3. **Synchronized Network Injection & IPC Barrier**
To prevent race conditions during namespace isolation, the Host Manager and the Bridge process utilize a two-way kernel pipe barrier. The Host Manager waits for the Bridge to unshare its network namespace. Once unshared, the Host Manager dynamically provisions a veth pair, injects the guest cable into the newly isolated namespace, and assigns the 10.0.0.1 switch gateway. The Host then signals the container via Inter-Process Communication to configure its own 10.0.0.2 IP address. This sequence ensures a fully operational network stack is guaranteed for the container before the payload ever boots.
4. **Dynamic Process Brain Transplant**
Vessel supports dynamic process replacement via the os.execvp system call. Because the network is pre-configured by the supervisor, the container can switch execution payloads based on your engineering goals.
Shell Mode: By executing ```sudo ./vessel-launcher.sh shell```, Vessel drops you into an interactive Alpine terminal. This mode is your diagnostic laboratory. Use Shell Mode when you are first learning the engine or debugging new filesystem mounts. It allows you to manually verify the chroot boundaries, test the automated virtual bridge using tools like ping, and observe how the kernel maps your isolated environment from the inside out.
SQL Mode: By executing ```sudo ./vessel-launcher.sh sql 1```, Vessel bypasses the interactive shell entirely to simulate a true cloud-native worker node. It programmatically provisions database socket directories, writes a dynamic SQL authorization script to the filesystem, and transplants its memory directly into the compiled mariadbd binary. The container boots silently in the background, fully wired to the host.
5. **Asynchronous Telemetry & Kernel IPC (telemetryTask.py)**
A native POSIX thread is spawned directly into the container's PID 1 memory space using ctypes and NPTL, operating independently of the Python Global Interpreter Lock. This watcher thread applies a kernel-level signal mask and enters a zero-CPU wait state using sigwait. Upon trapping a SIGUSR1 hardware interrupt from the host, it dynamically resolves its Cgroup v2 location via procfs and dumps real-time memory and CPU telemetry directly to the container's standard output.

### Prerequisites
Executing this engine requires a **native Linux environment**. It cannot be executed natively on macOS or Windows due to its reliance on Linux-specific system calls. Absolute root privileges (sudo) are mandatory to interact with the kernel namespace and cgroup subsystems.

# Quick Start
1.	Clone this repository to your Linux host environment.
2.	Execute sudo ```./vessel-launcher.sh shell``` to download the core filesystem, mirror the host DNS, compile external tools, and prepare the static container golden image at /tmp/vessel-root-base.
3.	Launch the runtime engine in interactive shell mode by executing sudo ```./vessel-launcher.sh shell```. You can immediately execute ```ping 10.0.0.1``` to verify the automated host network bridge is active.
4.	Verify your isolation by running ```ps x``` inside the spawned login shell to confirm your supervisor is operating as PID 1 and your shell as a child payload.
5.	Exit the shell, and launch the engine in sharded database mode by executing sudo ```./vessel-launcher.sh sql shardCount```.
6.	Open a new host terminal and connect to the isolated database payload over the virtual bridge by executing ```mysql -h 10.0.0.2 -u mysql -pvesseladmin```.
7.	Test the asynchronous kernel IPC by locating the supervisor's host PID using ```ps -ef | grep vessel.py```, and executing ```sudo kill -10 [PID]```.
8.	Return to your primary terminal to observe the real-time Cgroup v2 telemetry dump triggered by the host interrupt.

### [Optional Fun](vethernet.md)
