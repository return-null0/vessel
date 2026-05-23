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

        if mode == "shell":
            host_fd = sys.stdin.fileno()
            original_tty_state = termios.tcgetattr(host_fd)
            def cleanup_terminal():
                termios.tcsetattr(host_fd, termios.TCSADRAIN, original_tty_state)
            atexit.register(cleanup_terminal)
            
            tty.setraw(host_fd)
            while True:
                r_fds, _, _ = select.select([host_fd, master_fd], [], [])
                if host_fd in r_fds:
                    user_input = os.read(host_fd, 1024)
                    if not user_input: break
                    os.write(master_fd, user_input)
                if master_fd in r_fds:
                    try:
                        container_output = os.read(master_fd, 1024)
                        if not container_output: break
                        os.write(sys.stdout.fileno(), container_output)
                    except OSError: break
            os.close(master_fd)
            termios.tcsetattr(host_fd, termios.TCSADRAIN, original_tty_state)
        else:
            os.waitpid(bridge_pid, 0)
        return

    os.close(ns_r)
    os.close(net_w)
    if master_fd is not None:
        os.close(master_fd)

    if libc.unshare(flags) != 0:
        os._exit(1)

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
    os.mknod(null_node, 0o20666, os.makedev(1, 3))
    
    os.chdir(ROOTFS_DIR)
    os.chroot(".")
    
    os.makedirs("/proc", exist_ok=True)
    subprocess.run(["mount", "-t", "proc", "proc", "/proc"], check=True)
    os.makedirs("/sys", exist_ok=True)
    subprocess.run(["mount", "-t", "sysfs", "sysfs", "/sys"], check=True)

    container_hostname = f"vessel-{mode}-{shard_id}"
    libc.sethostname(container_hostname.encode(), len(container_hostname))

    r, w = os.pipe()
    payload_pid = os.fork()

    if payload_pid > 0:
        os.close(r)
        os.write(w, b"G")
        os.close(w)
        os.waitpid(payload_pid, 0)
        os._exit(0)

    os.close(w)
    os.read(r, 1)
    os.close(r)
    os.setsid()

    null_fd = os.open("/dev/null", os.O_RDWR)
    os.dup2(null_fd, 0)
    if null_fd > 2: os.close(null_fd)

    if mode == "sql":
            os.makedirs("/data", exist_ok=True)
            # Ensure the bootstrap can write to the data dir
            subprocess.run(["chmod", "777", "/data"], check=True)

            if not os.path.exists("/data/mysql"):
                print("[Container Payload] Bootstrapping system tables...", flush=True)
                # Capture the output to identify if it is failing silently
                result = subprocess.run(["mariadb-install-db", "--user=root", "--datadir=/data"], 
                                        capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"BOOTSTRAP FAILED: {result.stderr}")
                    os._exit(1)

            os.execvp("/usr/bin/mariadbd", [
                "/usr/bin/mariadbd", 
                "--datadir=/data", 
                "--user=root", 
                "--port=3306",
                "--skip-networking=0",
                "--bind-address=0.0.0.0"
            ])
    else:
        os.execvp("/bin/sh", ["/bin/sh", "-l"])