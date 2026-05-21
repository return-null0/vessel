import os
import ctypes
import subprocess
import sys
import telemetryTask
import time
import threading
import signal
import fcntl
import termios
import tty
import select
import errno
import atexit

def launch_vessel():
    print("[Host Manager] Initializing Vessel runtime engine...", flush=True)

    libc = ctypes.CDLL(None)

    mode = sys.argv[1]
    shard_id = int(sys.argv[2])
    ROOTFS_DIR = f"/tmp/vessel-root_{shard_id}"

    host_iface = f"v-host{shard_id}"
    guest_iface = f"v-guest{shard_id}"
    guest_ip = f"10.0.0.{shard_id + 1}/24"

    CLONE_NEWNS  = 0x00020000
    CLONE_NEWPID = 0x20000000
    CLONE_NEWNET = 0x40000000
    flags = CLONE_NEWNS | CLONE_NEWPID | CLONE_NEWNET

    ns_r, ns_w = os.pipe()
    net_r, net_w = os.pipe()

    master_fd = None
    slave_fd = None
    if mode != "sql":
        master_fd, slave_fd = os.openpty()

    bridge_pid = os.fork()

    if bridge_pid > 0:
        os.close(ns_w)
        os.close(net_r)

        if slave_fd is not None:
            os.close(slave_fd)

        os.read(ns_r, 1)
        os.close(ns_r)

        print(f"[Host Manager] Namespace detected at PID {bridge_pid}. Injecting network...", flush=True)

        subprocess.run(["ip", "link", "add", host_iface, "type", "veth", "peer", "name", guest_iface], check=True)
        subprocess.run(["ip", "link", "set", guest_iface, "netns", str(bridge_pid)], check=True)
        subprocess.run(["ip", "link", "set", host_iface, "up"], check=True)
        subprocess.run(["ip", "link", "set", host_iface, "master", "vessel_br0"], check=True)

        os.write(net_w, b"N")
        os.close(net_w)

        if mode != "sql":
            host_fd = sys.stdin.fileno()
            original_tty_state = termios.tcgetattr(host_fd)

            def cleanup_terminal():
                termios.tcsetattr(host_fd, termios.TCSADRAIN, original_tty_state)
            atexit.register(cleanup_terminal)

            def handle_sigterm(signum, frame):
                sys.exit(0)
            signal.signal(signal.SIGTERM, handle_sigterm)

            def resize_pty(signum=None, frame=None):
                try:
                    winsz = fcntl.ioctl(host_fd, termios.TIOCGWINSZ, struct.pack('HHHH', 0, 0, 0, 0))
                    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsz)
                except OSError as e:
                    if e.errno in (errno.EIO, errno.EBADF, errno.EINTR):
                        pass
                    else:
                        raise
            import struct
            signal.signal(signal.SIGWINCH, resize_pty)
            resize_pty()

            try:
                tty.setraw(host_fd)
                while True:
                    r_fds, w_fds, e_fds = select.select([host_fd, master_fd], [], [])

                    if host_fd in r_fds:
                        user_input = os.read(host_fd, 1024)
                        if not user_input:
                            break
                        os.write(master_fd, user_input)

                    if master_fd in r_fds:
                        try:
                            container_output = os.read(master_fd, 1024)
                            if not container_output:
                                break
                            os.write(sys.stdout.fileno(), container_output)
                            sys.stdout.flush()
                        except OSError:
                            break
            finally:
                os.close(master_fd)
                termios.tcsetattr(host_fd, termios.TCSADRAIN, original_tty_state)
        else:
            try:
                os.waitpid(bridge_pid, 0)
            except OSError as e:
                if e.errno != errno.ECHILD:
                    raise

        print("\n[Host Manager] Vessel execution concluded. Returning control to host.", flush=True)
        return

    os.close(ns_r)
    os.close(net_w)

    if master_fd is not None:
        os.close(master_fd)

    if libc.unshare(flags) != 0:
        print("[Bridge] FATAL: Failed to unshare kernel namespaces.", flush=True)
        os._exit(1)

    os.setsid()

    os.write(ns_w, b"R")
    os.close(ns_w)

    os.read(net_r, 1)
    os.close(net_r)

    supervisor_pid = os.fork()
    if supervisor_pid > 0:
        with open(f"{ROOTFS_DIR}/supervisor.pid", "w") as f:
            f.write(str(supervisor_pid))

        os.waitpid(supervisor_pid, 0)
        os._exit(0)

    subprocess.run(["/sbin/ip", "link", "set", guest_iface, "up"], check=True)
    subprocess.run(["/sbin/ip", "addr", "add", guest_ip, "dev", guest_iface], check=True)

    subprocess.run(["mount", "--make-rprivate", "/"], check=True)

    dev_dir = f"{ROOTFS_DIR}/dev"
    if not os.path.exists(dev_dir):
        os.makedirs(dev_dir, exist_ok=True)

    subprocess.run(["mount", "-t", "tmpfs", "tmpfs", dev_dir], check=True)
    S_IFCHR = 0x2000
    
    null_node = f"{dev_dir}/null"
    if not os.path.exists(null_node):
        os.mknod(null_node, S_IFCHR | 0o666, os.makedev(1, 3))
        
    zero_node = f"{dev_dir}/zero"
    if not os.path.exists(zero_node):
        os.mknod(zero_node, S_IFCHR | 0o666, os.makedev(1, 5))
        
    pts_dir = f"{dev_dir}/pts"
    os.makedirs(pts_dir, exist_ok=True)
    subprocess.run(["mount", "--bind", "/dev/pts", pts_dir], check=True)

    os.chdir(ROOTFS_DIR)
    os.chroot(".")

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

    r, w = os.pipe()

    payload_pid = os.fork()

    if payload_pid > 0:
        os.close(r)

        signal.pthread_sigmask(signal.SIG_BLOCK, [10])
        print("\n[PID 1 Supervisor] Runtime and Network established. Spawning telemetry...", flush=True)
        telemetryTask.start_blocking_watcher()

        os.write(w, b"G")
        os.close(w)

        os.waitpid(payload_pid, 0)
        os._exit(0)

    os.close(w)
    os.read(r, 1)
    os.close(r)

    while True:
        r, w = os.pipe()
        payload_pid = os.fork()

        if payload_pid > 0:
            os.close(r)
            os.write(w, b"G")
            os.close(w)

            _, status = os.waitpid(payload_pid, 0)

            if mode != "sql":
                print("\n[PID 1 Supervisor] Shell session ended. Shutting down container...", end="\r\n", flush=True)
                break

            print(f"\n[PID 1 Supervisor] Payload died (Status {status}). Restarting in 2s...", flush=True)
            time.sleep(2)
            continue

        os.close(w)
        os.read(r, 1)
        os.close(r)

        os.setsid()

        if mode != "sql" and slave_fd is not None:
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
        else:
            null_fd = os.open("/dev/null", os.O_RDWR)
            os.dup2(null_fd, 0)
            os.dup2(null_fd, 1)
            os.dup2(null_fd, 2)
            if null_fd > 2:
                os.close(null_fd)
            if slave_fd is not None:
                os.close(slave_fd)

        if mode == "sql":
            if not os.path.exists("/run/mysqld"):
                os.makedirs("/run/mysqld", mode=0o777, exist_ok=True)
            os.makedirs("/data", exist_ok=True)
            subprocess.run(["chown", "-R", "mysql:mysql", "/run/mysqld"], check=False)
            subprocess.run(["chown", "-R", "mysql:mysql", "/data"], check=False)

            if not os.path.exists("/data/mysql"):
                print("[Container Payload] Bootstrapping system tables...", flush=True)
                subprocess.run(["mariadb-install-db", "--user=root", "--datadir=/data"], check=True)

            init_sql_path = "/run/mysqld/init.sql"
            with open(init_sql_path, "w") as f:
                f.write("CREATE USER IF NOT EXISTS 'mysql'@'10.0.0.1' IDENTIFIED BY 'vesseladmin';\n")
                f.write("GRANT ALL PRIVILEGES ON *.* TO 'mysql'@'10.0.0.1';\n")
                f.write("FLUSH PRIVILEGES;\n")
            subprocess.run(["chown", "mysql:mysql", init_sql_path], check=False)

            os.execvp("/usr/bin/mariadbd", [
                "/usr/bin/mariadbd", "--datadir=/data", "--user=root", "--bind-address=0.0.0.0",
                "--skip-networking=0", "--port=3306", "--skip-name-resolve", f"--init-file={init_sql_path}"
            ])
        else:
            print("\r\n[Container Payload] Initialization complete. Welcome to Vessel Shell.", end="\r\n", flush=True)
            os.execvp("/bin/sh", ["/bin/sh", "-l"])

if __name__ == "__main__":
    launch_vessel()