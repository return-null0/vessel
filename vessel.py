import os
import ctypes
import subprocess

ROOTFS_DIR = "/tmp/vessel-root"

def launch_vessel():
    print("Initializing Vessel runtime engine...")

    libc = ctypes.CDLL(None)
    
    CLONE_NEWNS = 0x00020000   
    CLONE_NEWPID = 0x20000000  
    CLONE_NEWNET = 0x40000000  
    flags = CLONE_NEWNS | CLONE_NEWPID | CLONE_NEWNET
    
    if libc.unshare(flags) != 0:
        print("Fatal: Failed to unshare kernel namespaces. Use sudo.")
        exit(1)

    child_pid = os.fork()
    if child_pid > 0:
        os.waitpid(child_pid, 0)
        print("Vessel container terminated. Returning to host.")
        exit(0)

    os.chdir(ROOTFS_DIR)
    os.chroot(".")

    if not os.path.exists("/proc"):
        os.mkdir("/proc")
    subprocess.run(["mount", "-t", "proc", "proc", "/proc"], check=True)

    print("Welcome to Vessel. You are now running as PID 1.")
    os.execvp("/bin/sh", ["/bin/sh", "-l"])

if __name__ == "__main__":
    launch_vessel()
