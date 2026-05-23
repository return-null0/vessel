import os
import sys
import ctypes

CLONE_NEWNS = 0x00020000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000
MS_REC = 0x4000
MS_PRIVATE = 1 << 18

libc = ctypes.CDLL("libc.so.6", use_errno=True)

def apply_cgroup_constraints():
    print("Provisioning cgroup constraints...")

    cgroup_path = "/sys/fs/cgroup/vessel_sandbox"
    os.makedirs(cgroup_path, exist_ok=True)

    with open(os.path.join(cgroup_path, "memory.max"), "w") as f:
        f.write("500000000")

    with open(os.path.join(cgroup_path, "cgroup.procs"), "w") as f:
        f.write(str(os.getpid()))

def isolate_namespaces():
    print("Unsharing kernel namespaces...")

    if libc.unshare(CLONE_NEWNS | CLONE_NEWPID | CLONE_NEWNET) != 0:
        raise OSError(f"unshare failed: {os.strerror(ctypes.get_errno())}")

    libc.mount(None, b"/", None, MS_REC | MS_PRIVATE, None)

    libc.mount(b"proc", b"/proc", b"proc", 0, None)

def launch_payload():
    print("Forking into the new PID namespace...")

    pid = os.fork()

    if pid == 0:
        java_path = "/usr/bin/java"
        jar_path = "vessel-engine/target/vessel-engine-0.0.1-SNAPSHOT.jar"

        os.execvp("/usr/bin/tini", ["tini", "--", java_path, "-jar", jar_path])
    else:
        try:
            _, status = os.waitpid(pid, 0)
            sys.exit(os.waitstatus_to_exitcode(status))
        except KeyboardInterrupt:
            print("\nShutting down vessel engine supervisor...")
            sys.exit(0)

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Fatal: Vessel supervisor requires root privileges.")
        sys.exit(1)

    apply_cgroup_constraints()
    isolate_namespaces()
    launch_payload()