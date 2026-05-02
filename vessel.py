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
    
    child_pid = os.fork()
    if child_pid > 0:
        os.waitpid(child_pid,0)
        print("Vessel manager terminated. Returning to host.")
        return

    if libc.unshare(flags) != 0:
        print("Fatal: Failed to unshare kernel namespaces. Use sudo.")
        os._exit(1)

    grandchild_pid = os.fork()
    if grandchild_pid > 0:
        # Wait for the container to exit.
        os.waitpid(grandchild_pid, 0)
        print("Vessel container terminated. Returning to manager.")
        os._exit(0)

    # We are now the child process. We are officially PID 1.
    # It is now safe to spawn subprocesses because PID 1 will stay alive.
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)

    os.chdir(ROOTFS_DIR)
    os.chroot(".")


    if not os.path.exists("/proc"):
        os.mkdir("/proc")
    subprocess.run(["mount", "-t", "proc", "proc", "/proc"], check=True)

    print("Welcome to Vessel. You are now running as PID 1.")
    os.execvp("/bin/sh", ["/bin/sh", "-l"])

if __name__ == "__main__":
    launch_vessel()


"""
	1.	The Master forks the Middle Child.
	2.	The Master calls os.waitpid() on the Middle Child.
	3.	The Middle Child forks the Grandchild (the container).
	4.	The Middle Child calls os.waitpid() on the Grandchild.
"""

