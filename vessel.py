import os
import ctypes
import subprocess

import telemetryTask

ROOTFS_DIR = "/tmp/vessel-root"

def launch_vessel():
    print("Initializing Vessel runtime engine...")

    libc = ctypes.CDLL(None)
    
    CLONE_NEWNS = 0x00020000   
    CLONE_NEWPID = 0x20000000  
    CLONE_NEWNET = 0x40000000  
    flags = CLONE_NEWNS | CLONE_NEWPID | CLONE_NEWNET
    
    child_pid = os.fork()
    if child_pid > 0:
        os.waitpid(child_pid, 0)
        print("Vessel manager terminated. Returning to host.")
        return

    if libc.unshare(flags) != 0:
        print("Fatal: Failed to unshare kernel namespaces. Use sudo.")
        os._exit(1)
    
    grandchild_pid = os.fork()
    if grandchild_pid > 0:
        os.waitpid(grandchild_pid, 0)
        print("Vessel container terminated. Returning to manager.")
        os._exit(0)

    # We are now the child process. We are officially PID 1 in the new namespace.
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)

    os.chdir(ROOTFS_DIR)
    os.chroot(".")

    # Existing proc mount
    if not os.path.exists("/proc"):
        os.mkdir("/proc")
    subprocess.run(["mount", "-t", "proc", "proc", "/proc"], check=True)

    # 1. Mount the core sysfs (Hardware and Kernel Objects)
    if not os.path.exists("/sys"):
        os.mkdir("/sys")
    subprocess.run(["mount", "-t", "sysfs", "sysfs", "/sys"], check=True)

    # 2. Mount the cgroup v2 hierarchy
    cgroup_dir = "/sys/fs/cgroup"
    if not os.path.exists(cgroup_dir):
        os.makedirs(cgroup_dir, exist_ok=True)
    subprocess.run(["mount", "-t", "cgroup2", "cgroup2", cgroup_dir], check=True)

    # Launch the blocking watcher inside the container namespace
    telemetryTask.start_blocking_watcher()


    # Split the Supervisor from the Payload
    payload_pid = os.fork()
    
    if payload_pid > 0:
        # SUPERVISOR: This stays as a Python process.
        # Because we NEVER call execvp here, the thread stays in memory.
        print("[Vessel] Supervisor active. Thread ID exists in task folder.")
        os.waitpid(payload_pid, 0)
        os._exit(0)
        
    print("Welcome to Vessel. Shell payload initializing.")
    os.execvp("/bin/sh", ["/bin/sh", "-l"])

if __name__ == "__main__":
    launch_vessel()
