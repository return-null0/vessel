import os
import ctypes
import subprocess
import sys
import telemetryTask

ROOTFS_DIR = "/tmp/vessel-root"

def launch_vessel():
    print("[Host Manager] Initializing Vessel runtime engine...", flush=True)

    libc = ctypes.CDLL(None)
    
    # Define Linux clone flags for namespace isolation
    CLONE_NEWNS  = 0x00020000  # Mount namespace
    CLONE_NEWPID = 0x20000000  # PID namespace
    CLONE_NEWNET = 0x40000000  # Network namespace
    flags = CLONE_NEWNS | CLONE_NEWPID | CLONE_NEWNET
    
    # 1. FORK THE NAMESPACE BRIDGE (Middle Child)
    # The Host Manager stays behind to anchor the terminal and catch the exit code.



    bridge_pid = os.fork()
    if bridge_pid > 0:
        os.waitpid(bridge_pid, 0)
        print("[Host Manager] Vessel execution concluded. Returning control to host.", flush=True)
        return

    # 2. SEVER KERNEL TIES
    # The Bridge process detaches from the host's namespaces via unshare.
    if libc.unshare(flags) != 0:
        print("[Bridge] FATAL: Failed to unshare kernel namespaces. Root privileges (sudo) required.", flush=True)
        os._exit(1)
    
    # 3. FORK THE SUPERVISOR (Grandchild)
    # The Bridge must fork again so the new process is officially born as PID 1 
    # inside the newly isolated PID namespace.


    supervisor_pid = os.fork()
    if supervisor_pid > 0:
        os.waitpid(supervisor_pid, 0)
        os._exit(0)

    # --- ISOLATION BOUNDARY CROSSED ---
    # Execution is now strictly within the context of Container PID 1.
    
    # 4. CONFIGURE MOUNT NAMESPACE
    # Mark the root filesystem as private to prevent container mounts from leaking back to the host OS.
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)

    # Transition the process root into the provisioned Alpine filesystem.
    os.chdir(ROOTFS_DIR)
    os.chroot(".")

    # 5. INITIALIZE VIRTUAL FILESYSTEMS
    # Mount procfs for process identity and namespace tracking.
    if not os.path.exists("/proc"):
        os.mkdir("/proc")
    subprocess.run(["mount", "-t", "proc", "proc", "/proc"], check=True)

    # Mount sysfs for hardware and kernel object tracking.
    if not os.path.exists("/sys"):
        os.mkdir("/sys")
    subprocess.run(["mount", "-t", "sysfs", "sysfs", "/sys"], check=True)

    # Mount the unified Cgroup v2 hierarchy for resource telemetry.
    cgroup_dir = "/sys/fs/cgroup"
    if not os.path.exists(cgroup_dir):
        os.makedirs(cgroup_dir, exist_ok=True)
    subprocess.run(["mount", "-t", "cgroup2", "cgroup2", cgroup_dir], check=True)
        # 6. CREATE THE KERNEL PIPE BARRIER
    # r = read end, w = write end
    r, w = os.pipe()

    # 7. FORK THE INTERACTIVE PAYLOAD
    payload_pid = os.fork()
    
    if payload_pid > 0:
        # SUPERVISOR (Parent)
        os.close(r) # The parent only writes, so we close the read end
        
        print("[PID 1 Supervisor] Runtime established. Spawning telemetry thread...", flush=True)
        telemetryTask.start_blocking_watcher()
        
        # Send 1 byte down the pipe to unblock the payload
        os.write(w, b"G")
        os.close(w)
        
        os.waitpid(payload_pid, 0)
        os._exit(0)
        
    # PAYLOAD (Child)
    os.close(w) # The child only reads, so we close the write end
    
    # This is a blocking system call. The CPU will consume 0 cycles here 
    # until the parent writes the byte to the pipe.
    os.read(r, 1)
    os.close(r)
    
    print("[Container Payload] Initialization complete. Welcome to Vessel.", flush=True)
    os.execvp("/bin/sh", ["/bin/sh", "-l"])


if __name__ == "__main__":
    launch_vessel()
