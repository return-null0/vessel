import os
import sys
import time
import ctypes
import subprocess
import termios
import signal
import fcntl
import errno
import tty
import select
import atexit
import json
import threading
import http.server
import socketserver
import datetime

libc = ctypes.CDLL("libc.so.6", use_errno=True)
SIGSET_SIZE = 128 

RESTART_ALLOWED = [True] 
ACTIVE_PID = [0]

def signal_watcher_callback(arg):
    sig_set = (ctypes.c_char * SIGSET_SIZE)()
    libc.sigemptyset(ctypes.byref(sig_set))
    libc.sigaddset(ctypes.byref(sig_set), 10) 

    print("\r[Thread] Signal Watcher PARKED. Waiting for SIGUSR1 (10)...", flush=True)
    
    sig_received = ctypes.c_int(0)
    while True:
        res = libc.sigwait(ctypes.byref(sig_set), ctypes.byref(sig_received))
        
        if res == 0 and sig_received.value == 10:
            try:
                with open("/proc/1/cgroup", "r") as f:
                    cgroup_suffix = f.read().strip().split("::")[1]
                
                cgroup_path = f"/sys/fs/cgroup{cgroup_suffix}"
                
                with open(f"{cgroup_path}/memory.current", "r") as f:
                    mem_mb = int(f.read().strip()) / (1024 * 1024)
                
                cpu_sec = 0.0
                with open(f"{cgroup_path}/cpu.stat", "r") as f:
                    for line in f.readlines():
                        if line.startswith("usage_usec"):
                            cpu_sec = int(line.split()[1]) / 1_000_000
                            break

                with open(f"{cgroup_path}/pids.current", "r") as f:
                    total_threads = int(f.read().strip())

                stats = {
                    "memory_mb": round(mem_mb, 2),
                    "cpu_sec": round(cpu_sec, 4),
                    "total_threads": total_threads
                }
                with open("/telemetry.json", "w") as f:
                    json.dump(stats, f)

            except Exception as e:
                pass
                
    return None

CALLBACK_FUNC = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)
c_signal_callback = CALLBACK_FUNC(signal_watcher_callback)

def start_blocking_watcher():
    mask = (ctypes.c_char * SIGSET_SIZE)()
    libc.sigemptyset(ctypes.byref(mask))
    libc.sigaddset(ctypes.byref(mask), 10)
    libc.pthread_sigmask(0, ctypes.byref(mask), None)

    thread_id = ctypes.c_uint64(0)
    libc.pthread_create.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_void_p, CALLBACK_FUNC, ctypes.c_void_p]
    
    res = libc.pthread_create(ctypes.byref(thread_id), None, c_signal_callback, None)
    if res == 0:
        libc.pthread_detach(thread_id)

# Add this global at the top of launch_vessel or as a global
active_payload_pid = [0] 

def launch_telemetry_trigger():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/telemetry':
                os.kill(os.getpid(), 10)
                time.sleep(0.15)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                with open("/telemetry.json", "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == '/kill':
                # Intentional shutdown: Stop restarting the child
                RESTART_ALLOWED[0] = False
                if ACTIVE_PID[0] > 0:
                    os.kill(ACTIVE_PID[0], signal.SIGKILL)
                
                self.send_response(200)
                self.end_headers()
                
            elif self.path == '/restart':
                # Graceful restart: Allow the supervisor to loop again
                RESTART_ALLOWED[0] = True
                if ACTIVE_PID[0] > 0:
                    os.kill(ACTIVE_PID[0], signal.SIGTERM)
                
                self.send_response(200)
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

    httpd = socketserver.TCPServer(("0.0.0.0", 9090), Handler)
    httpd.serve_forever()

def launch_vessel():
    print("[Host Manager] Initializing Vessel runtime engine...", flush=True)
    libc_core = ctypes.CDLL(None)

    mode = sys.argv[1]
    shard_id = int(sys.argv[2])
    total_shards = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "" else "3"
    
    ROOTFS_DIR = f"/tmp/vessel-root_{shard_id}"
    host_iface = f"v-host{shard_id}"
    guest_iface = f"v-guest{shard_id}"
    guest_ip = f"10.0.0.{shard_id + 1}/24"

    CLONE_NEWNS  = 0x00020000
    CLONE_NEWUTS = 0x04000000
    CLONE_NEWPID = 0x20000000
    CLONE_NEWNET = 0x40000000
    flags = CLONE_NEWNS | CLONE_NEWUTS | CLONE_NEWPID | CLONE_NEWNET

    ns_r, ns_w = os.pipe()
    net_r, net_w = os.pipe()

    master_fd = None
    slave_fd = None
    if mode == "shell":
        master_fd, slave_fd = os.openpty()

    bridge_pid = os.fork()

    if bridge_pid > 0:
        os.close(ns_w)
        os.close(net_r)
        if slave_fd is not None: os.close(slave_fd)
        os.read(ns_r, 1)
        os.close(ns_r)

        subprocess.run(["ip", "link", "add", host_iface, "type", "veth", "peer", "name", guest_iface], check=True)
        subprocess.run(["ip", "link", "set", guest_iface, "netns", str(bridge_pid)], check=True)
        subprocess.run(["ip", "link", "set", host_iface, "up"], check=True)
        subprocess.run(["ip", "link", "set", host_iface, "master", "vessel_br0"], check=True)

        os.write(net_w, b"N")
        os.close(net_w)

        if mode == "shell":
            host_fd = sys.stdin.fileno()
            original_tty_state = termios.tcgetattr(host_fd)
            def cleanup_terminal(): termios.tcsetattr(host_fd, termios.TCSADRAIN, original_tty_state)
            atexit.register(cleanup_terminal)
            tty.setraw(host_fd)
            while True:
                r_fds, _, _ = select.select([host_fd, master_fd], [], [])
                if host_fd in r_fds:
                    ui = os.read(host_fd, 1024)
                    if not ui: break
                    os.write(master_fd, ui)
                if master_fd in r_fds:
                    try:
                        co = os.read(master_fd, 1024)
                        if not co: break
                        os.write(sys.stdout.fileno(), co)
                    except OSError: break
            os.close(master_fd)
            termios.tcsetattr(host_fd, termios.TCSADRAIN, original_tty_state)
        else:
            os.waitpid(bridge_pid, 0)
        return

    os.close(ns_r)
    os.close(net_w)
    if master_fd is not None: os.close(master_fd)
    if libc_core.unshare(flags) != 0: os._exit(1)

    os.setsid()
    os.write(ns_w, b"R")
    os.close(ns_w)
    os.read(net_r, 1)
    os.close(net_r)

    supervisor_pid = os.fork()
    if supervisor_pid > 0:
        os.waitpid(supervisor_pid, 0)
        os._exit(0)

    time.sleep(0.5)
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    subprocess.run(["ip", "link", "set", guest_iface, "up"], check=True)
    subprocess.run(["ip", "addr", "add", guest_ip, "dev", guest_iface], check=True)
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)
    
    dev_dir = f"{ROOTFS_DIR}/dev"
    os.makedirs(dev_dir, exist_ok=True)
    subprocess.run(["mount", "-t", "tmpfs", "tmpfs", dev_dir], check=True)
    
    null_node = f"{dev_dir}/null"
    if not os.path.exists(null_node): os.mknod(null_node, 0o20666, os.makedev(1, 3))
    
    os.chdir(ROOTFS_DIR)
    os.chroot(".")
    
    os.makedirs("/proc", exist_ok=True)
    subprocess.run(["mount", "-t", "proc", "proc", "/proc"], check=True)
    os.makedirs("/sys", exist_ok=True)
    subprocess.run(["mount", "-t", "sysfs", "sysfs", "/sys"], check=True)
    
    os.makedirs("/sys/fs/cgroup", exist_ok=True)
    subprocess.run(["mount", "-t", "cgroup2", "none", "/sys/fs/cgroup"], check=False)

    os.makedirs("/run", exist_ok=True)
    subprocess.run(["mount", "-t", "tmpfs", "tmpfs", "/run"], check=True)

    libc_core.sethostname(f"vessel-{mode}-{shard_id}".encode(), len(f"vessel-{mode}-{shard_id}"))

    start_blocking_watcher()
    threading.Thread(target=launch_telemetry_trigger, daemon=True).start()

    # Ensure this is defined outside the loop in launch_vessel
    active_payload_pid = [0] 

    while True:
        r, w = os.pipe()
        pid = os.fork()
        
        if pid > 0:
            # SUPERVISOR LOGIC
            os.close(r)
            os.write(w, b"G")
            os.close(w)
            
            ACTIVE_PID[0] = pid
            _, status = os.waitpid(pid, 0)
            
            # Watchdog Logic: Did the child die because we killed it, or did it crash?
            if RESTART_ALLOWED[0]:
                print(f"[Watchdog] Child {pid} exited unexpectedly. Restarting in 2s...", flush=True)
                time.sleep(2)
                continue
            else:
                print(f"[Watchdog] Shutdown requested. Cleaning up Supervisor.", flush=True)
                os._exit(0)

        # CHILD PROCESS LOGIC
        os.close(w)
        os.read(r, 1)
        os.close(r)
        os.setsid()

        null_fd = os.open("/dev/null", os.O_RDWR)
        os.dup2(null_fd, 0)
        if null_fd > 2: os.close(null_fd)

        if mode == "sql":
            os.makedirs("/run/mysqld", mode=0o777, exist_ok=True)
            db_dir = "/var/lib/mysql"
            os.makedirs(db_dir, exist_ok=True)
            subprocess.run(["chmod", "777", db_dir], check=False)
            init_sql_path = "/tmp/init.sql"
            
            # Optimization: Only run install-db if the mysql system tables don't exist
            if not os.path.exists(os.path.join(db_dir, "mysql")):
                subprocess.run(["mariadb-install-db", "--user=root", f"--datadir={db_dir}"], check=True)
                
            with open(init_sql_path, "w") as f:
                f.write("CREATE DATABASE IF NOT EXISTS appdata;\n")
                f.write("CREATE USER IF NOT EXISTS 'mysql'@'%' IDENTIFIED BY 'vesseladmin';\n")
                f.write("GRANT ALL PRIVILEGES ON *.* TO 'mysql'@'%' WITH GRANT OPTION;\n")
                f.write("FLUSH PRIVILEGES;\n")
                f.write("USE appdata;\n")
                f.write("CREATE TABLE IF NOT EXISTS cluster_data (id VARCHAR(50) PRIMARY KEY, payload VARCHAR(255), origin_shard INT, created_at DATETIME);\n")
                
                now = datetime.datetime.now()
                events = ["Kernel initialized", "VFS mounted", "Network bridge up", "MariaDB engine started", "Cgroups assigned", "Socket bound to 0.0.0.0", "Telemetry daemon active", "User authentication required"]
                
                for j in range(1, 16):
                    event_time = (now - datetime.timedelta(minutes=30-j)).strftime("%Y-%m-%d %H:%M:%S")
                    event_text = events[j % len(events)]
                    record_id = f"V-SHARD{shard_id}-R{j:04d}"
                    # Use INSERT IGNORE to prevent crashes on restart due to Primary Key collision
                    f.write(f"INSERT IGNORE INTO cluster_data (id, payload, origin_shard, created_at) VALUES ('{record_id}', '{event_text}', {shard_id}, '{event_time}');\n")
                
                f.write("FLUSH PRIVILEGES;\n")
            
            subprocess.run(["chmod", "644", init_sql_path], check=False)
                
            os.execvp("/usr/bin/mariadbd", [
                "/usr/bin/mariadbd", f"--datadir={db_dir}", "--user=root", "--port=3306",
                "--socket=/run/mysqld/mysqld.sock", "--skip-networking=0", "--bind-address=0.0.0.0",
                "--skip-name-resolve", f"--init-file={init_sql_path}"
            ])
        
        elif mode == "spring":
            java_bin = "/usr/lib/jvm/java-21-openjdk/bin/java" 
            env = {
                "PATH": "/usr/lib/jvm/java-21-openjdk/bin:/usr/bin:/bin",
                "LD_LIBRARY_PATH": "/usr/lib/jvm/java-21-openjdk/lib/server:/usr/lib",
                "JAVA_HOME": "/usr/lib/jvm/java-21-openjdk",
                "VESSEL_SHARD_COUNT": total_shards
            }
            os.execvpe(java_bin, [java_bin, "-Dserver.address=0.0.0.0", "-jar", "/app/vessel-engine.jar"], env)

        else:
            os.execvp("/bin/sh", ["/bin/sh", "-l"])

if __name__ == "__main__":
    launch_vessel()