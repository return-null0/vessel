import os
import platform
import urllib.request
import subprocess
import shutil

current_arch = platform.machine()
arch_map = {
    "x86_64": "x86_64",
    "aarch64": "aarch64",
    "armv7l": "armv7",
    "i686": "x86"
}

alpine_arch = arch_map.get(current_arch, "x86_64")

ALPINE_VERSION = "3.23"
TARBALL_URL = f"https://dl-cdn.alpinelinux.org/alpine/v3.23/releases/{alpine_arch}/alpine-minirootfs-3.23.4-{alpine_arch}.tar.gz"
ROOTFS_DIR = "/tmp/vessel-root-base"
TARBALL_PATH = "/tmp/alpine-rootfs.tar.gz"

def provision_rootfs():
    print("Starting Vessel provisioning...")

    if os.path.exists(ROOTFS_DIR):
        shutil.rmtree(ROOTFS_DIR)
    os.makedirs(ROOTFS_DIR)

    print(f"Fetching root file system for: {alpine_arch}")
    urllib.request.urlretrieve(TARBALL_URL, TARBALL_PATH)

    print("Extracting file hierarchy...")
    subprocess.run(["tar", "-xzf", TARBALL_PATH, "-C", ROOTFS_DIR], check=True)
    os.remove(TARBALL_PATH)

    print("Injecting custom profile configuration...")
    profile_dir = os.path.join(ROOTFS_DIR, "root")
    os.makedirs(profile_dir, exist_ok=True)
    with open(os.path.join(profile_dir, ".profile"), "w") as f:
        print(r"export PS1='\033[1;32mvessel\033[0m:\033[1;34m\w\033[0m# '", file=f)

    print("Injecting universal container DNS configuration...")
    resolv_dir = os.path.join(ROOTFS_DIR, "etc")
    os.makedirs(resolv_dir, exist_ok=True)
    resolv_target = os.path.join(resolv_dir, "resolv.conf")

    with open(resolv_target, "w") as f:
        f.write("nameserver 1.1.1.1\n")
        f.write("nameserver 8.8.8.8\n")

    print("Preparing chroot environment (Binding system interfaces)...")
    for d in ["proc", "dev", "sys"]:
        os.makedirs(os.path.join(ROOTFS_DIR, d), exist_ok=True)

    try:
        subprocess.run(["mount", "--bind", "/proc", os.path.join(ROOTFS_DIR, "proc")], check=True)
        subprocess.run(["mount", "--bind", "/dev", os.path.join(ROOTFS_DIR, "dev")], check=True)
        subprocess.run(["mount", "--bind", "/sys", os.path.join(ROOTFS_DIR, "sys")], check=True)

        print("Executing package installation...")
        subprocess.run(["chroot", ROOTFS_DIR, "apk", "update"], check=True)
        subprocess.run(["chroot", ROOTFS_DIR, "apk", "add", "vim"], check=True)
        subprocess.run(["chroot", ROOTFS_DIR, "apk", "add", "mariadb"], check=True)
        subprocess.run(["chroot", ROOTFS_DIR, "apk", "add", "mc"], check=True)

        subprocess.run(["chroot", ROOTFS_DIR, "apk", "add", "openjdk21-jre"], check=True)

    except subprocess.CalledProcessError as e:
        print(f"Fatal error during package injection: {e}")
        exit(1)
    finally:
        print("Cleaning up chroot bindings...")
        subprocess.run(["umount", os.path.join(ROOTFS_DIR, "proc")], check=False)
        subprocess.run(["umount", os.path.join(ROOTFS_DIR, "dev")], check=False)
        subprocess.run(["umount", os.path.join(ROOTFS_DIR, "sys")], check=False)

    print("Injecting compiled Spring Boot payload into rootfs...")
    app_dir = os.path.join(ROOTFS_DIR, "app")
    os.makedirs(app_dir, exist_ok=True)

    jar_source = "vessel-engine/target/vessel-engine-0.0.1-SNAPSHOT.jar"
    jar_target = os.path.join(app_dir, "vessel-engine.jar")
    shutil.copy(jar_source, jar_target)

    print("Provisioning successful.")

if __name__ == "__main__":
    provision_rootfs()