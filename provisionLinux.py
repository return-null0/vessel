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
    print(f"Starting Vessel provisioning with Alpine {ALPINE_VERSION}...")

    # Step 1: Clean 
    if os.path.exists(ROOTFS_DIR):
        print(f"Wiping existing filesystem at {ROOTFS_DIR}...")
        shutil.rmtree(ROOTFS_DIR)
    os.makedirs(ROOTFS_DIR)

    # Step 2: Download the tarball
    print(f"Downloading root filesystem from {TARBALL_URL}...")
    urllib.request.urlretrieve(TARBALL_URL, TARBALL_PATH)
    print("Download complete.")

    # Step 3: Extract using the kernel's native tar binary
    print(f"Extracting file hierarchy to {ROOTFS_DIR} using native tar...")
    try:
        subprocess.run(
            ["tar", "-xzf", TARBALL_PATH, "-C", ROOTFS_DIR],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Fatal OS error during extraction. Kernel reported:\n{e.stderr}")
        exit(1)
    
    # Step 4: Cleanup
    print("Removing temporary tarball...")
    os.remove(TARBALL_PATH)
    
    print(f"Provisioning successful. The sandbox at {ROOTFS_DIR} is ready for chroot.")

if __name__ == "__main__":
    provision_rootfs()
