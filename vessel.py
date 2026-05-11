import os
import ctypes
import subprocess
import sys
import telemetryTask

ROOTFS_DIR = "/tmp/vessel-root"

def launch_vessel():
    print("[Host Manager] Initializing Vessel runtime engine...", flush=True)

    libc = ctypes.CDLL(None)
    
    mode = sys.argv[1]

    CLONE_NEWNS  = 0x00020000  
    CLONE_NEWPID = 0x20000000  
    CLONE_NEWNET = 0x40000000  
    flags = CLONE_NEWNS | CLONE_NEWPID | CLONE_NEWNET
    
    # Create two pipes to synchronize the network handoff
    # ns_pipe: Bridge tells Host namespace is unshared and ready
    # net_pipe: Host tells Bridge cable is injected, proceed
    ns_r, ns_w = os.pipe()
    net_r, net_w = os.pipe()

    # 1. FORK THE NAMESPACE BRIDGE
    bridge_pid = os.fork()
    
    if bridge_pid > 0:
        # --- HOST MANAGER ---
        os.close(ns_w)
        os.close(net_r)

        # Block the Host Manager until the Bridge unshares its namespace
        os.read(ns_r, 1)
        os.close(ns_r)

        print(f"[Host Manager] Namespace detected at PID {bridge_pid}. Injecting network...", flush=True)
        
        subprocess.run(["ip", "link", "add", "v-host", "type", "veth", "peer", "name", "v-guest"], check=True)
        subprocess.run(["ip", "link", "set", "v-guest", "netns", str(bridge_pid)], check=True)
        subprocess.run(["ip", "addr", "add", "10.0.0.1/24", "dev", "v-host"], check=True)
        subprocess.run(["ip", "link", "set", "v-host", "up"], check=True)

        # Unblock the Bridge so it can configure its side of the cable
        os.write(net_w, b"N")
        os.close(net_w)

        os.waitpid(bridge_pid, 0)
        print("[Host Manager] Vessel execution concluded. Returning control to host.", flush=True)
        return

    # --- BRIDGE PROCESS ---
    os.close(ns_r)
    os.close(net_w)

    # 2. SEVER KERNEL TIES
    if libc.unshare(flags) != 0:
        print("[Bridge] FATAL: Failed to unshare kernel namespaces.", flush=True)
        os._exit(1)
    
    # Tell the Host Manager the namespace is built
    os.write(ns_w, b"R")
    os.close(ns_w)

    # Block the Bridge until the Host Manager finishes throwing the cable through the wall
    os.read(net_r, 1)
    os.close(net_r)
    
    # 3. FORK THE SUPERVISOR
    supervisor_pid = os.fork()
    if supervisor_pid > 0:
        os.waitpid(supervisor_pid, 0)
        os._exit(0)

    # --- PID 1 SUPERVISOR ---
    # Configure the container side of the network BEFORE we chroot.


    subprocess.run(["ip", "link", "set", "v-guest", "up"], check=True)
    subprocess.run(["ip", "addr", "add", "10.0.0.2/24", "dev", "v-guest"], check=True)

    # 4. CONFIGURE MOUNT NAMESPACE
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)

    os.chdir(ROOTFS_DIR)
    os.chroot(".")

    # 5. INITIALIZE VIRTUAL FILESYSTEMS
    if not os.path.exists("/proc"):
        os.mkdir("/proc")
    subprocess.run(["mount", "-t", "proc", "proc", "/proc"], check=True)

    if not os.path.exists("/sys"):
        os.mkdir("/sys")
    subprocess.run(["mount", "-t", "sysfs", "sysfs", "/sys"], check=True)

    cgroup_dir = "/sys/fs/cgroup"
    if not os.path.exists(cgroup_dir):
        os.makedirs(cgroup_dir, exist_ok=True)
    subprocess.run(["mount", "-t", "cgroup2", "cgroup2", cgroup_dir], check=True)

    # 6. PAYLOAD SYNCHRONIZATION
    r, w = os.pipe()

    # 7. FORK THE PAYLOAD
    payload_pid = os.fork()
    
    if payload_pid > 0:
        os.close(r) 
        
        print("[PID 1 Supervisor] Runtime and Network established. Spawning telemetry...", flush=True)
        telemetryTask.start_blocking_watcher()
        
        os.write(w, b"G")
        os.close(w)
        
        os.waitpid(payload_pid, 0)
        os._exit(0)
        
    os.close(w) 
    os.read(r, 1)
    os.close(r)

    if mode == "sql":
        print("[Container Payload] Provisioning database directories and credentials...", flush=True)
        
        if not os.path.exists("/run/mysqld"):
            os.makedirs("/run/mysqld", mode=0o777, exist_ok=True)
            
        os.makedirs("/data", exist_ok=True)

        subprocess.run(["chown", "-R", "mysql:mysql", "/run/mysqld"], check=False)
        subprocess.run(["chown", "-R", "mysql:mysql", "/data"], check=False)

        print("[Container Payload] Bootstrapping system tables...", flush=True)
        subprocess.run([
            "mariadb-install-db", 
            "--user=mysql", 
            "--datadir=/data"
        ], check=True)

        init_sql_path = "/run/mysqld/init.sql"
        with open(init_sql_path, "w") as f:
            f.write("CREATE USER IF NOT EXISTS 'mysql'@'10.0.0.1' IDENTIFIED BY 'vesseladmin';\n")
            f.write("GRANT ALL PRIVILEGES ON *.* TO 'mysql'@'10.0.0.1';\n")
            f.write("FLUSH PRIVILEGES;\n")

            
        # Ensure the mysql user can read the temporary file
        subprocess.run(["chown", "mysql:mysql", init_sql_path], check=False)

        print("[Container Payload] Booting MariaDB Daemon directly as PID 1...", flush=True)
        os.execvp("/usr/bin/mariadbd", [
            "/usr/bin/mariadbd", 
            "--datadir=/data", 
            "--user=mysql", 
            "--bind-address=0.0.0.0",
            "--skip-networking=0",
            "--port=3306",
            "--skip-name-resolve",
            f"--init-file={init_sql_path}"
        ])
    else:
        print("[Container Payload] Initialization complete. Welcome to Vessel.", flush=True)
        os.execvp("/bin/sh", ["/bin/sh", "-l"])



if __name__ == "__main__":
    launch_vessel()
