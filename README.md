# Vessel
A minimal Linux container engine designed to demonstrate the fundamentals of OS-level virtualization.
<details>
<summary><b>View Photo 1: Resource Caging & Host Handshake</b></summary>

<img src="pics/pic1.png" width="800px">

The initial execution phase anchors the engine to the hardware. Before the Python supervisor boots, the shell wrapper carves out a sanctuary in the Cgroup v2 unified hierarchy.

**Key Detail:** Notice the cpu.stat dump. This confirms the kernel is actively tracking execution microseconds and enforcing the 100000 / 100000 quota (100% of a single core).
</details>

<details>
<summary><b>View Photo 2: Namespace Mapping & Identity</b></summary>

<img src="pics/pic2.png" width="800px">

By inspecting the kernel status of the process tasks, we can verify the physical separation of the container's identity from the host.

**Key Detail:** The NSpid 7 entry shows the kernel has re-indexed the background telemetry thread to a local ID of 7, independent of its actual PID on the host. This confirms the PID namespace is active, allowing us to target this specific thread for telemetry interrupts without conflict, while ensuring the container remains strictly isolated from the host's global process table.
</details>

<details>
<summary><b>View Photo 3: Asynchronous Telemetry & IPC</b></summary>

<img src="pics/pic3.png" width="800px">

The final architectural pillar is the Asynchronous Heartbeat. This demonstrates a persistent, non-blocking telemetry channel that survives the execvp payload swap.

**Key Detail:** The Ghost Processes count of 2 reveals the invisible host anchors (the Manager and Bridge) that are still technically part of this cgroup, providing a 360-degree view of the sandbox's resource footprint.
</details>


## Overview
Vessel bypasses high-level abstractions like Docker or containerd to interface directly with the Linux kernel. It constructs isolated environments using raw system calls, kernel namespaces, control groups, and an automated virtual network bridge. This project serves as a bare-metal implementation of a container runtime, proving that containers are simply a specific configuration of native Linux security features and routing tables rather than standalone virtual machines.
The engine natively provisions a host-to-container ethernet connection on every boot, providing a persistent network bridge. Vessel is explicitly designed with a dual-mode architecture, allowing you to seamlessly transition between an interactive learning environment (shell mode) and a headless, production-grade infrastructure deployment (sql mode).

## Core Architecture and Execution Flow
The engine relies on a physically separated architecture, utilizing distinct Linux kernel mechanisms spread across four primary components to establish an impenetrable container boundary with real-time telemetry and basic network access.

1. Build-Phase Software Injection `provisionLinux.py`
This script acts as the infrastructure compiler. It provisions an Alpine Linux Mini Root Filesystem, dynamically mirrors the host machine's DNS routing configuration, and handles the compilation and injection of external software directly into the static filesystem image before runtime isolation occurs.
2. Resource Caging & Initialization `vessel-launcher.sh`
This shell script serves as the resource manager and execution entry point. It interfaces directly with the host kernel's Cgroup v2 pseudo-filesystem to construct the sandbox environment. It performs legacy state cleanup, applies strict hardware ceilings for CPU time slices, and securely locks its own process into the cgroup tree before handing execution over to the Python engine.
3. Triple-Fork Isolation & Supervisor Pattern  `vessel.py`
The runtime engine utilizes a synchronized multi-fork pattern to transition from the host environment into the isolated container without mutating the original caller. The Manager Process forks a supervisor and waits for its completion, ensuring the host's terminal state is preserved. The Namespace Supervisor (Middle Child) executes the unshare system call with CLONE_NEWNS, CLONE_NEWPID, and CLONE_NEWNET flags, severing kernel relationships and marking the root filesystem as private to prevent mount leaks. The Container Init (Grandchild) crosses the PID boundary to become PID 1, performs the final chroot into the provisioned rootfs, and mounts the private /proc and /sys pseudo-filesystems.

4. Synchronized Network Injection & IPC Barrier
To prevent race conditions during namespace isolation, the Host Manager and the Bridge process utilize a two-way kernel pipe barrier. The Host Manager waits for the Bridge to unshare its network namespace. Once unshared, the Host Manager dynamically provisions a veth pair, injects the guest cable into the newly isolated namespace, and assigns the 10.0.0.1 gateway. The Host then signals the container via IPC to configure its own 10.0.0.2 IP address. This sequence ensures a fully operational network stack is guaranteed for the container before the payload ever boots.

5. Dynamic Process Brain Transplant

Vessel supports dynamic process replacement via the os.execvp system call. Because the network is pre-configured by the supervisor, the container can effortlessly switch execution payloads based on your engineering goals.

**Shell Mode**: By executing `sudo python3 vessel.py shell`, Vessel drops you into an interactive Alpine terminal. This mode is your diagnostic laboratory. It is highly advised to use Shell Mode when you are first learning the engine or debugging new filesystem mounts. It allows you to manually verify the chroot boundaries, test the automated 10.0.0.1 network bridge using tools like `ping`, and observe how the kernel maps your isolated environment from the inside out.

**SQL Mode**: By executing `sudo python3 vessel.py sql`, Vessel bypasses the interactive shell entirely to simulate a true cloud-native worker node. It programmatically provisions database socket directories, writes a dynamic SQL authorization script to the filesystem, and transplants its memory directly into the compiled mariadbd binary. The container boots silently in the background, fully wired to the host. It is advised to transition to SQL Mode once you understand the sandbox fundamentals, as it demonstrates exactly how enterprise orchestration engines run headless, secure network services without human intervention.

7. Asynchronous Telemetry & Kernel IPC `telemetryTask.py`
A native POSIX thread is spawned directly into the container's PID 1 memory space using ctypes and NPTL, operating independently of the Python Global Interpreter Lock. This watcher thread applies a kernel-level signal mask and enters a zero-CPU wait state using sigwait. Upon trapping a SIGUSR1 hardware interrupt from the host, it dynamically resolves its Cgroup v2 location via procfs and dumps real-time memory and CPU telemetry directly to the container's standard output.



• The Manager Process: Forks a supervisor and waits for its completion. This ensures the host's terminal state is preserved and the main script remains a "clean" host citizen.

• The Namespace Supervisor (Middle Child): Executes the unshare system call with CLONE_NEWNS, CLONE_NEWPID, and CLONE_NEWNET flags. It marks the root filesystem as private (--make-rprivate) to prevent mount leaks back to the host.

• The Container Init (Grandchild): Crossed the PID namespace boundary to become PID 1. It performs the final chroot into the provisioned rootfs, mounts a private /proc pseudo-filesystem, and executes the login shell. This process remains the sole owner of the terminal's stdin until exit.

---

## Prerequisites
Executing this engine requires a native Linux environment or a lightweight hypervisor. It cannot be executed natively on macOS or Windows due to its reliance on Linux-specific system calls. Absolute root privileges (sudo) are mandatory to interact with the kernel namespace and cgroup subsystems.
### Quick Start
1.	Clone this repository to your Linux host environment.
2.	Execute `sudo python3 provisionLinux.py` to download the core filesystem, mirror the host DNS, compile Vim, and prepare the static container image at /tmp/vessel-root.
3.	Launch the runtime engine in interactive shell mode by executing `sudo python3 vessel.py shell`. You can immediately execute ping 10.0.0.1 to verify the automated host network bridge is active.
4.	Verify your isolation by running `ps x` inside the spawned login shell to confirm your supervisor is operating as PID 1 and your shell as a child payload.
5.	Exit the shell, and launch the engine in SQL mode by executing `sudo python3 vessel.py sql`.
6.	Open a new host terminal and connect to the isolated database payload over the virtual bridge by executing `mysql -h 10.0.0.2 -u mysql -pvesseladmin`.
7.	Test the asynchronous kernel IPC by locating the supervisor's host PID using `ps -ef | grep vessel.py`, and executing `sudo kill -10 [PID]`.
8.	Return to your primary terminal to observe the real-time Cgroup v2 telemetry dump triggered by the host interrupt.

### [Optional Fun](vethernet.md)
