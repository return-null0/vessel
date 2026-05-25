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
SIGSET_SIZE = 128 
RESTART_ALLOWED = [True] 
ACTIVE_PID = [0]

def signal_watcher_callback(arg):
    sig_set = (ctypes.c_char * SIGSET_SIZE)()
    libc.sigemptyset(ctypes.byref(sig_set))
    libc.sigaddset(ctypes.byref(sig_set), 10) 
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
                stats = {"memory_mb": round(mem_mb, 2)}
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
                with open("/telemetry.json", "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
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
            st = termios.tcgetattr(host_fd)
            tty.setraw(host_fd)
            try:
                while True:
                    r, _, _ = select.select([host_fd, master_fd], [], [])
                    if host_fd in r:
                        ui = os.read(host_fd, 1024)
                        if not ui: break
                        os.write(master_fd, ui)
                    if master_fd in r:
                        try:
                            co = os.read(master_fd, 1024)
                            if not co: break
                            os.write(sys.stdout.fileno(), co)
                        except OSError: break
            finally:
                termios.tcsetattr(host_fd, termios.TCSADRAIN, st)
        else:
            os.waitpid(pid, 0)
        return

    # CHILD: Container Configuration
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
    subprocess.run(["/bin/mount", "--make-rprivate", "/"], check=True)
    dev_dir = f"{ROOTFS_DIR}/dev"
    os.makedirs(dev_dir, exist_ok=True)
    subprocess.run(["/bin/mount", "-t", "tmpfs", "tmpfs", dev_dir], check=True)
    if not os.path.exists(f"{dev_dir}/null"): os.mknod(f"{dev_dir}/null", 0o20666, os.makedev(1, 3))
    if not os.path.exists(f"{dev_dir}/ptmx"): os.mknod(f"{dev_dir}/ptmx", 0o666, os.makedev(5, 2))
    os.chdir(ROOTFS_DIR); os.chroot(".")
    for d in ["/proc", "/sys", "/sys/fs/cgroup", "/run"]: os.makedirs(d, exist_ok=True)
    subprocess.run(["/bin/mount", "-t", "proc", "proc", "/proc"], check=True)
    subprocess.run(["/bin/mount", "-t", "sysfs", "sysfs", "/sys"], check=True)
    subprocess.run(["/bin/mount", "-t", "tmpfs", "tmpfs", "/run"], check=True)
    start_blocking_watcher()
    threading.Thread(target=launch_telemetry_trigger, daemon=True).start()
    
    while True:
        r, w = os.pipe()
        pid = os.fork()
        if pid > 0:
            os.close(r); os.write(w, b"G"); os.close(w)
            _, status = os.waitpid(pid, 0)
            print(f"[DEBUG] Child {pid} exited with code: {os.waitstatus_to_exitcode(status)}", flush=True)
            if mode != "shell" and RESTART_ALLOWED[0]:
                time.sleep(2); continue
            os._exit(0)

        os.close(w); os.read(r, 1); os.close(r); os.setsid()
        
        cgroup_dir = f"/sys/fs/cgroup/vessel_cluster/vessel_sandbox_{shard_id}"
        if os.path.exists(cgroup_dir):
            with open(f"{cgroup_dir}/cgroup.procs", "w") as f:
                f.write(str(os.getpid()))

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
            env = {"PATH": "/usr/bin:/bin", "JAVA_HOME": "/usr/lib/jvm/java-21-openjdk", "LD_LIBRARY_PATH": "/usr/lib"}
            os.execvpe("/usr/bin/java", ["java", "-Xms64m", "-Xmx256m", "-jar", "/app/vessel-engine.jar"], env)
        else:
            os.execvp("/bin/sh", ["/bin/sh", "-l"])

if __name__ == "__main__":
    launch_vessel()