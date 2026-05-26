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
import shutil

libc = ctypes.CDLL("libc.so.6", use_errno=True)
libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_void_p]
SIGSET_SIZE = 128 
RESTART_ALLOWED = [True] 
ACTIVE_PID = [0]
MS_REC = 16384
MS_PRIVATE = 262144
MS_BIND = 4096


def handle_signal(signum, frame):
    if ACTIVE_PID[0] > 0:
        try:
            os.kill(ACTIVE_PID[0], signum)
        except OSError:
            pass
    os._exit(0)

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

def do_mount(source, target, fstype, flags=0):
    res = libc.mount(source.encode(), target.encode(), fstype.encode(), flags, None)
    if res != 0:
        err = ctypes.get_errno()
        if err != errno.EBUSY:
            raise OSError(err, f"Mount {fstype} failed on {target}: {os.strerror(err)}")

def signal_watcher_callback(arg):
    sig_set = (ctypes.c_char * SIGSET_SIZE)()
    libc.sigemptyset(ctypes.byref(sig_set))
    libc.sigaddset(ctypes.byref(sig_set), 10) 
    sig_received = ctypes.c_int(0)
    while True:
        res = libc.sigwait(ctypes.byref(sig_set), ctypes.byref(sig_received))
        if res == 0 and sig_received.value == 10:
            try:
                with open("/proc/self/cgroup", "r") as f:
                    cgroup_suffix = f.read().split("0::")[1].strip()
                cgroup_path = f"/sys/fs/cgroup{cgroup_suffix}"
                
                with open(os.path.join(cgroup_path, "memory.current"), "r") as f:
                    mem_mb = int(f.read().strip()) / (1024 * 1024)
                
                cpu_use = 0
                with open(os.path.join(cgroup_path, "cpu.stat"), "r") as f:
                    for line in f:
                        if line.startswith("usage_usec"):
                            cpu_use = int(line.split()[1])
                            break
                
                stats = {"memory_mb": round(mem_mb, 2), "cpu_usec": cpu_use}
                with open("/telemetry.json", "w") as f:
                    json.dump(stats, f)
            except Exception:
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
                if os.path.exists("/telemetry.json"):
                    with open("/telemetry.json", "rb") as f:
                        self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                
        def do_POST(self):
            if self.path == '/kill':
                self.send_response(200)
                self.end_headers()
                RESTART_ALLOWED[0] = False
                if ACTIVE_PID[0] > 0:
                    try:
                        os.kill(ACTIVE_PID[0], signal.SIGTERM)
                    except OSError:
                        pass
            elif self.path == '/restart':
                self.send_response(200)
                self.end_headers()
                RESTART_ALLOWED[0] = True
                if ACTIVE_PID[0] > 0:
                    try:
                        os.kill(ACTIVE_PID[0], signal.SIGTERM)
                    except OSError:
                        pass
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            return
            
    httpd = socketserver.TCPServer(("0.0.0.0", 9090), Handler)
    httpd.serve_forever()

def launch_vessel():
    if len(sys.argv) < 3:
        sys.exit(1)
    mode = sys.argv[1]
    shard_id = int(sys.argv[2])
    ROOTFS_DIR = f"/tmp/vessel-root_{shard_id}"
    subprocess.run(["/sbin/ip", "link", "del", f"v-host{shard_id}"], stderr=subprocess.DEVNULL)
    flags = 0x00020000 | 0x04000000 | 0x20000000 | 0x40000000 
    ns_pipe_r, ns_pipe_w = os.pipe()
    net_pipe_r, net_pipe_w = os.pipe()
    master_fd, slave_fd = None, None
    if mode == "shell": master_fd, slave_fd = os.openpty()
    pid = os.fork()
    
    if pid > 0:
        os.close(ns_pipe_w); os.close(net_pipe_r)
        if slave_fd is not None: os.close(slave_fd)
        try:
            if os.read(ns_pipe_r, 1) != b"S": os._exit(1)
        except OSError: os._exit(1)
        os.close(ns_pipe_r)
        host_iface = f"v-host{shard_id}"
        guest_iface = f"v-guest{shard_id}"
        subprocess.run(["/sbin/ip", "link", "add", host_iface, "type", "veth", "peer", "name", guest_iface], check=True)
        subprocess.run(["/sbin/ip", "link", "set", guest_iface, "netns", str(pid)], check=True)
        subprocess.run(["/sbin/ip", "link", "set", host_iface, "up"], check=True)
        subprocess.run(["/sbin/ip", "link", "set", host_iface, "master", "vessel_br0"], check=True)
        os.write(net_pipe_w, b"G"); os.close(net_pipe_w)
        if mode == "shell":
            host_fd = sys.stdin.fileno()
            st = None
            
            if os.isatty(host_fd):
                st = termios.tcgetattr(host_fd)
                tty.setraw(host_fd)
            else:
                print("[WARNING] Input is not a TTY. Interactive shell features will be limited.", flush=True)
                
            try:
                while True:
                    r, _, _ = select.select([host_fd, master_fd], [], [])
                    if host_fd in r:
                        try:
                            ui = os.read(host_fd, 1024)
                            if not ui: break
                            os.write(master_fd, ui)
                        except OSError:
                            break
                    if master_fd in r:
                        try:
                            co = os.read(master_fd, 1024)
                            if not co: break
                            os.write(sys.stdout.fileno(), co)
                        except OSError: 
                            break
            finally:
                if st is not None:
                    termios.tcsetattr(host_fd, termios.TCSADRAIN, st)
        else:
            os.waitpid(pid, 0)
        return

    os.close(ns_pipe_r); os.close(net_pipe_w)
    if master_fd is not None: os.close(master_fd)
    
    libc_core = ctypes.CDLL(None)
    if libc_core.unshare(flags) != 0: os._exit(1)
    
    os.setsid()
    supervisor_pid = os.fork()
    if supervisor_pid > 0:
        os.waitpid(supervisor_pid, 0)
        os._exit(0)
    
    os.write(ns_pipe_w, b"S"); os.close(ns_pipe_w)
    os.read(net_pipe_r, 1); os.close(net_pipe_r)
    
    subprocess.run(["/sbin/ip", "link", "set", "lo", "up"], check=True)
    subprocess.run(["/sbin/ip", "link", "set", f"v-guest{shard_id}", "up"], check=True)
    subprocess.run(["/sbin/ip", "addr", "add", f"10.0.0.{shard_id+1}/24", "dev", f"v-guest{shard_id}"], check=True)
    
    for d in ["proc", "sys", "sys/fs/cgroup", "run", "tmp", "dev"]:
        target = os.path.join(ROOTFS_DIR, d)
        if os.path.islink(target):
            os.unlink(target)
        os.makedirs(target, exist_ok=True)
        
    do_mount("none", "/", "none", MS_PRIVATE | MS_REC) 
    do_mount("proc", os.path.join(ROOTFS_DIR, "proc"), "proc")
    do_mount("sysfs", os.path.join(ROOTFS_DIR, "sys"), "sysfs")
    do_mount("cgroup2", os.path.join(ROOTFS_DIR, "sys/fs/cgroup"), "cgroup2")
    do_mount("tmpfs", os.path.join(ROOTFS_DIR, "run"), "tmpfs")
    do_mount("tmpfs", os.path.join(ROOTFS_DIR, "tmp"), "tmpfs")
    do_mount("tmpfs", os.path.join(ROOTFS_DIR, "dev"), "tmpfs")
    
    pts_dir = os.path.join(ROOTFS_DIR, "dev/pts")
    os.makedirs(pts_dir, exist_ok=True)
    do_mount("/dev/pts", pts_dir, "none", MS_BIND)
    
    os.chmod(os.path.join(ROOTFS_DIR, "tmp"), 0o1777)
    
    dev_dir = os.path.join(ROOTFS_DIR, "dev")
    libc.mknod(os.path.join(dev_dir, "null").encode(), 0o20666, os.makedev(1, 3))
    libc.mknod(os.path.join(dev_dir, "zero").encode(), 0o20666, os.makedev(1, 5))
    libc.mknod(os.path.join(dev_dir, "random").encode(), 0o20666, os.makedev(1, 8))
    libc.mknod(os.path.join(dev_dir, "urandom").encode(), 0o20666, os.makedev(1, 9))
    libc.mknod(os.path.join(dev_dir, "tty").encode(), 0o20666, os.makedev(5, 0))
    libc.mknod(os.path.join(dev_dir, "ptmx").encode(), 0o666, os.makedev(5, 2))
    
    os.chdir(ROOTFS_DIR)
    os.chroot(".")
    os.chdir("/")

    cgroup_dir = f"/sys/fs/cgroup/vessel_cluster/vessel_sandbox_{shard_id}"
    if os.path.exists(cgroup_dir):
        try:
            with open(f"{cgroup_dir}/cgroup.procs", "w") as f:
                f.write(str(os.getpid()))
        except Exception: pass
    
    start_blocking_watcher()
    threading.Thread(target=launch_telemetry_trigger, daemon=True).start()
    
    while True:
        r, w = os.pipe()
        pid = os.fork()
        if pid > 0:
            ACTIVE_PID[0] = pid
            os.close(r); os.write(w, b"G"); os.close(w)
            _, status = os.waitpid(pid, 0)
            exit_code = os.waitstatus_to_exitcode(status)
            print(f"[DEBUG] Child {pid} exited with code:{exit_code}", end="\r", flush=True)
            if mode != "shell" and RESTART_ALLOWED[0]:
                time.sleep(5); continue
            os._exit(0)

        os.close(w); os.read(r, 1); os.close(r); os.setsid()

        if mode == "shell":
            try:
                fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            except Exception:
                pass

            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)

            env = {
                "PATH": "/bin:/usr/bin:/sbin:/usr/sbin",
                "TERM": "xterm-256color",
                "HOME": "/root",
                "USER": "root",
                "PS1": "\033[36mvessel\033[0m:\033[32m\\w\033[0m# "
            }
            
            os.execvpe("/bin/sh", ["/bin/sh", "-i"], env)
        elif mode == "spring":
            if not os.path.exists("/usr/bin/java"):
                sys.stderr.write("FATAL: Java not found inside chroot.\n")
                os._exit(1)
            if not os.path.exists("/app/vessel-engine.jar"):
                sys.stderr.write("FATAL: /app/vessel-engine.jar not found.\n")
                os._exit(1)
                
            print("[DEBUG] Launching Spring Boot Router...", flush=True)
            env = {"PATH": "/usr/bin:/bin", "JAVA_HOME": "/usr/lib/jvm/java-21-openjdk", "LD_LIBRARY_PATH": "/usr/lib"}
            os.execvpe("/usr/bin/java", ["java", "-Xms64m", "-Xmx256m", "-Djava.io.tmpdir=/tmp", "-jar", "/app/vessel-engine.jar"], env)
        elif mode == "sql":
            env = {"PATH": "/bin:/usr/bin:/sbin:/usr/sbin"}
            
            os.makedirs("/run/mysqld", exist_ok=True)
            os.makedirs("/var/lib/mysql", exist_ok=True)
            
            with open("/var/lib/mysql/init.sql", "w") as f:
                f.write("CREATE DATABASE IF NOT EXISTS appdata;\n")
                f.write("USE appdata;\n")
                f.write("""CREATE TABLE IF NOT EXISTS cluster_data (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            shard_key VARCHAR(255),
                            payload TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );\n""")
                
                for i in range(1, 51):
                    unique_key = f"shard_{shard_id}_idx_{i}"
                    unique_payload = f"Payload item {i} generated for node {shard_id}"
                    f.write(f"INSERT INTO cluster_data (shard_key, payload) VALUES ('{unique_key}', '{unique_payload}');\n")
                
            subprocess.run(["chown", "-R", "mysql:mysql", "/run/mysqld", "/var/lib/mysql"], env=env, check=False)
            if not os.path.exists("/var/lib/mysql/mysql"):
                install_bin = "/usr/bin/mariadb-install-db"
                if not os.path.exists(install_bin):
                    install_bin = "/usr/bin/mysql_install_db"
                
                if not os.path.exists(install_bin):
                    sys.stderr.write("FATAL: MariaDB initialization binary not found.\n")
                    os._exit(1)

                print(f"[DEBUG] Initializing MariaDB data directory using {install_bin}...", flush=True)
                subprocess.run([install_bin, "--user=mysql", "--datadir=/var/lib/mysql"], env=env, check=False)
            
            print("[DEBUG] Launching mysqld daemon...", flush=True)
            os.execvpe("mysqld", [
                "mysqld", 
                "--user=mysql", 
                "--datadir=/var/lib/mysql", 
                "--socket=/run/mysqld/mysqld.sock",
                "--port=3306",
                "--bind-address=0.0.0.0",
                "--skip-networking=0",
                "--skip-grant-tables",
                "--skip-name-resolve",  
                "--init-file=/var/lib/mysql/init.sql"
            ], env)
        else:
            os.execvp("/bin/sh", ["/bin/sh", "-l"])

if __name__ == "__main__":
    launch_vessel()