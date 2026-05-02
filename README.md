# Vessel
A minimal Linux container engine designed to demonstrate the fundamentals of OS-level virtualization.

## Overview
Vessel bypasses high-level abstractions like Docker or containerd to interface directly with the Linux kernel. It constructs isolated environments using raw system calls, kernel namespaces, and control groups. This project serves as a bare-metal implementation of a container runtime, proving that containers are simply a specific configuration of native Linux security features rather than standalone virtual machines.

## Core Architecture and Execution Flow
The engine relies on a physically separated build-and-run architecture, utilizing distinct Linux kernel mechanisms spread across three primary scripts to establish an impenetrable container boundary.

1. Build-Phase Software Injection `provisionLinux.py`
This script acts as the infrastructure compiler. It provisions an Alpine Linux Mini Root Filesystem, dynamically mirrors the host machine's DNS routing configuration, and handles the compilation and injection of external software (such as Vim and Midnight Commander) directly into the static filesystem image before runtime isolation occurs.
2. Resource Caging & Initialization `vessel-launcher.sh`
This shell script serves as the resource manager and execution entry point. It interfaces directly with the host kernel's /sys/fs/cgroup pseudo-filesystem to construct the sandbox environment. It performs legacy state cleanup, applies strict hardware ceilings for CPU time slices and PID limits to prevent resource exhaustion, and securely locks its own process into the cgroup tree before handing execution over to the Python engine.
3. Synchronized Double-Fork Isolation `vessel.py`
The final runtime engine utilizes a Double-Fork and Namespace Unshare pattern to transition from the host environment into the isolated container without mutating the original caller.

• The Manager Process: Forks a supervisor and waits for its completion. This ensures the host's terminal state is preserved and the main script remains a "clean" host citizen.

• The Namespace Supervisor (Middle Child): Executes the unshare system call with CLONE_NEWNS, CLONE_NEWPID, and CLONE_NEWNET flags. It marks the root filesystem as private (--make-rprivate) to prevent mount leaks back to the host.

• The Container Init (Grandchild): Crossed the PID namespace boundary to become PID 1. It performs the final chroot into the provisioned rootfs, mounts a private /proc pseudo-filesystem, and executes the login shell. This process remains the sole owner of the terminal's stdin until exit.

## Prerequisites
Executing this engine requires a native Linux environment or a lightweight hypervisor. It cannot be executed natively on macOS or Windows due to its reliance on Linux-specific system calls. Absolute root privileges (sudo) are mandatory to interact with the kernel namespace and cgroup subsystems.
### Quick Start
1.	Clone this repository to your Linux host environment.
2.	Execute `sudo python3 provisionLinux.py` to download the core filesystem, mirror the host DNS, compile Vim, and prepare the static container image at /tmp/vessel-root.
3.	Launch the runtime engine by executing the resource wrapper via `sudo ./vessel-launcher.sh`.
4.	Verify your isolation by running ps x inside the spawned login shell to confirm your process is operating as PID 1, and execute vim to verify your software injection succeeded.