# Vessel

A minimal, from-scratch Linux container engine designed to demonstrate the fundamental primitives of OS-level virtualization.

<br>

# Overview
Vessel bypasses high-level abstractions like Docker or containerd to interface directly with the Linux kernel. It programmatically constructs isolated environments using raw system calls, kernel namespaces, and control groups. This project serves as a bare-metal implementation of a container runtime, proving that containers are simply a specific configuration of native Linux security features rather than standalone virtual machines.

<br>

# Core Architecture
The engine relies on three distinct Linux kernel mechanisms to establish an impenetrable container boundary.

<br>

## Filesystem Isolation (chroot)
The **provisionLinux** script provisions an Alpine Linux Mini Root Filesystem. Then on startup the program utilizes the chroot system call to restrict the child process entirely within this directory structure, preventing any file-level visibility into the host operating system.

## Process and Network Separation (Namespaces)
By executing the unshare system call with the `CLONE_NEWPID` and `CLONE_NEWNET` flags, the engine severs the child's connection to the host machine's process tree and network hardware. The containerized application is granted the illusion of being PID 1 inside a completely isolated network void.

## Resource Caging (cgroups v2)
The runtime dynamically generates a new Control Group directly within the /sys/fs/cgroup/ pseudo-filesystem. It enforces strict physical hardware limits by writing byte ceilings to memory.max before attaching the child's PID to the cgroup tree. This ensures the kernel's Out Of Memory (OOM) Killer will terminate the containerized process long before it can starve the host system's RAM.

<br>

# Prerequisites
Executing this engine requires a native Linux environment or a lightweight hypervisor like Multipass. It cannot be executed natively on macOS or Windows due to its reliance on Linux-specific system calls. Absolute root privileges (sudo) are mandatory to interact with the kernel namespace and cgroup subsystems.


## Quick Start
1.	Clone this repository to your Linux host environment.
2.	Execute the initialization script to download and untar the Alpine Mini Root Filesystem into /tmp/vessel-root.
3.	Launch the runtime engine as the root user.
4.	Verify your isolation by running ps aux inside the spawned shell to confirm your process is operating as PID 1.