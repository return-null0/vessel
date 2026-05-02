import os
import urllib.request
import subprocess
import shutil

# Configure configuration parameters
ALPINE_VERSION = "3.23"
TARBALL_URL = f"https://dl-cdn.alpinelinux.org/alpine/v3.23/releases/aarch64/alpine-minirootfs-3.23.4-aarch64.tar.gz"
ROOTFS_DIR = "/tmp/vessel-root"
TARBALL_PATH = "/tmp/alpine-rootfs.tar.gz"

def provision_rootfs():
    print("Starting Vessel provisioning...")

    if os.path.exists(ROOTFS_DIR):
        shutil.rmtree(ROOTFS_DIR)
    os.makedirs(ROOTFS_DIR)

    print("Downloading root filesystem...")
    urllib.request.urlretrieve(TARBALL_URL, TARBALL_PATH)

    print("Extracting file hierarchy...")
    subprocess.run(["tar", "-xzf", TARBALL_PATH, "-C", ROOTFS_DIR], check=True)
    os.remove(TARBALL_PATH)

    print("Injecting custom profile configuration...")
    profile_dir = os.path.join(ROOTFS_DIR, "root")
    os.makedirs(profile_dir, exist_ok=True)
    with open(os.path.join(profile_dir, ".profile"), "w") as f:
        print(r"export PS1='\033[1;32mvessel\033[0m:\033[1;34m\w\033[0m# '", file=f)

    print("Injecting universal DNS configuration...")
    # Step 4: Build-Phase Software Injection
    print("Injecting host-mirrored DNS configuration...")
    resolv_dir = os.path.join(ROOTFS_DIR, "etc")
    os.makedirs(resolv_dir, exist_ok=True)
    resolv_target = os.path.join(resolv_dir, "resolv.conf")
    
    # Dynamically locate the host's true DNS configuration
    host_resolv_paths = [
        "/run/systemd/resolve/resolv.conf", 
        "/run/systemd/resolve/stub-resolv.conf", 
        "/etc/resolv.conf"
    ]
    
    host_resolv = None
    for path in host_resolv_paths:
        if os.path.exists(path):
            host_resolv = path
            break
            
    if host_resolv:
        # Read the raw text to avoid copying broken symlinks
        with open(host_resolv, "r") as src, open(resolv_target, "w") as dst:
            dst.write(src.read())
    else:
        # Ultimate fallback to systemd local stub
        with open(resolv_target, "w") as f:
            f.write("nameserver 127.0.0.53\n")

    print("Executing chroot package installation (Requires Host Network)...")
    try:
        subprocess.run(
            ["chroot", ROOTFS_DIR, "apk", "update"],
            check=True
        )
        subprocess.run(
            ["chroot", ROOTFS_DIR, "apk", "add", "vim"],
            check=True
        )

        subprocess.run(
            ["chroot", ROOTFS_DIR, "apk", "add", "mc"],
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Fatal error during package injection. Kernel reported:\n{e.stderr}")
        exit(1)

    print("Cleaning up temporary DNS configuration...")
    os.remove(resolv_target)

    print("Provisioning successful.")

if __name__ == "__main__":
    provision_rootfs()

