import os
import platform
import urllib.request
import subprocess
import shutil
import sys

current_arch = platform.machine()
arch_map = {
    "x86_64": "x86_64",
    "aarch64": "aarch64",
    "armv7l": "armv7",
    "i686": "x86"
}
alpine_arch = arch_map.get(current_arch, "x86_64")

ALPINE_VERSION = "3.23"
TARBALL_URL = f"https://dl-cdn.alpinelinux.org/alpine/v{ALPINE_VERSION}/releases/{alpine_arch}/alpine-minirootfs-{ALPINE_VERSION}.4-{alpine_arch}.tar.gz"
ROOTFS_DIR = "/tmp/vessel-root-base"
TARBALL_PATH = "/tmp/alpine-rootfs.tar.gz"

def run_chroot(cmd):
    result = subprocess.run(["chroot", ROOTFS_DIR] + cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result

def provision_rootfs():
    print(f"--- Starting Vessel provisioning ({alpine_arch}) ---")

    if os.path.exists(ROOTFS_DIR):
        shutil.rmtree(ROOTFS_DIR)
    os.makedirs(ROOTFS_DIR)

    print(f"Fetching Alpine {ALPINE_VERSION} rootfs...")
    try:
        urllib.request.urlretrieve(TARBALL_URL, TARBALL_PATH)
    except Exception as e:
        print(f"Failed to download rootfs: {e}")
        sys.exit(1)

    print("Extracting filesystem...")
    subprocess.run(["tar", "-xzf", TARBALL_PATH, "-C", ROOTFS_DIR], check=True)
    os.remove(TARBALL_PATH)

    print("Injecting host DNS configuration...")
    os.makedirs(os.path.join(ROOTFS_DIR, "etc"), exist_ok=True)
    shutil.copyfile("/etc/resolv.conf", os.path.join(ROOTFS_DIR, "etc/resolv.conf"))

    print("Mounting system interfaces...")
    for d in ["proc", "dev", "sys"]:
        path = os.path.join(ROOTFS_DIR, d)
        os.makedirs(path, exist_ok=True)
        subprocess.run(["mount", "--bind", f"/{d}", path], check=True)

    try:
        print("Updating package database...")
        run_chroot(["apk", "update"])

        pkgs = ["vim", "mariadb", "mc", "openjdk21", "libstdc++"]
        for pkg in pkgs:
            print(f"Installing {pkg}...")
            run_chroot(["apk", "add", pkg])

        print("Configuring dynamic linker for Java...")
        lib_conf_dir = os.path.join(ROOTFS_DIR, "etc/ld.so.conf.d")
        os.makedirs(lib_conf_dir, exist_ok=True)
        
        ld_conf = os.path.join(lib_conf_dir, "java.conf")
        lib_path = "/usr/lib/jvm/java-21-openjdk/lib/server"
        
        with open(ld_conf, "w") as f:
            f.write(lib_path)
        run_chroot(["ldconfig"])

    except subprocess.CalledProcessError as e:
        print(f"Fatal error during package installation: {e}")
        sys.exit(1)
    finally:
        print("Cleaning up mounts...")
        for d in ["proc", "dev", "sys"]:
            subprocess.run(["umount", os.path.join(ROOTFS_DIR, d)], check=False)

    print("Injecting compiled Spring Boot payload...")
    app_dir = os.path.join(ROOTFS_DIR, "app")
    os.makedirs(app_dir, exist_ok=True)
    jar_source = "vessel-engine/target/vessel-engine-0.0.1-SNAPSHOT.jar"
    jar_target = os.path.join(app_dir, "vessel-engine.jar")
    
    if os.path.exists(jar_source):
        shutil.copy(jar_source, jar_target)
    else:
        print(f"FATAL: JAR not found at {jar_source}. Did the Maven build succeed?")
        sys.exit(1)

    print("Provisioning successful.")

if __name__ == "__main__":
    if os.getuid() != 0:
        print("This script must be run as root.")
        sys.exit(1)
    provision_rootfs()