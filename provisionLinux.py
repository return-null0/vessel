import os
import platform
import urllib.request
import subprocess
import shutil
import sys

current_arch = platform.machine()
arch_map = {"x86_64": "x86_64", "aarch64": "aarch64", "armv7l": "armv7", "i686": "x86"}
alpine_arch = arch_map.get(current_arch, "x86_64")

ALPINE_VERSION = "3.23"
TARBALL_URL = f"https://dl-cdn.alpinelinux.org/alpine/v{ALPINE_VERSION}/releases/{alpine_arch}/alpine-minirootfs-{ALPINE_VERSION}.4-{alpine_arch}.tar.gz"
ROOTFS_DIR = "/var/lib/vessel/root-base"
TARBALL_PATH = "/var/lib/vessel/alpine-rootfs.tar.gz"

def run_chroot(cmd):
    result = subprocess.run(["chroot", ROOTFS_DIR] + cmd)
    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}")
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result

def inject_network_config():
    etc_dir = os.path.join(ROOTFS_DIR, "etc")
    os.makedirs(etc_dir, exist_ok=True)
    with open(os.path.join(etc_dir, "resolv.conf"), "w") as f:
        f.write("nameserver 8.8.8.8\nnameserver 1.1.1.1\n")
    with open(os.path.join(etc_dir, "nsswitch.conf"), "w") as f:
        f.write("hosts: files dns\n")

def provision_rootfs():
    if os.path.exists(ROOTFS_DIR):
        print("--- Rootfs cache detected. Refreshing network and skipping install. ---")
        inject_network_config()
    else:
        print(f"--- Starting fresh Vessel provisioning ({alpine_arch}) ---")
        os.makedirs(ROOTFS_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(TARBALL_PATH), exist_ok=True)
        
        print(f"Downloading Alpine minirootfs...")
        try:
            subprocess.run(
                ["curl", "-L", "--progress-bar", "-o", TARBALL_PATH, TARBALL_URL], 
                check=True
            )
        except subprocess.CalledProcessError:
            print("FATAL: Failed to download Alpine rootfs. Check your internet connection or DNS.")
            sys.exit(1)

        print("Extracting rootfs...")
        subprocess.run(["tar", "-xpf", TARBALL_PATH, "-C", ROOTFS_DIR], check=True)
        os.remove(TARBALL_PATH)
        inject_network_config()
        
        for d in ["proc", "dev", "sys"]:
            path = os.path.join(ROOTFS_DIR, d)
            os.makedirs(path, exist_ok=True)
            subprocess.run(["mount", "--bind", f"/{d}", path], check=True)

        try:
            print("Installing Alpine packages (this may take a minute)...")
            run_chroot(["apk", "update"])
            run_chroot(["apk", "add", "vim", "mariadb", "mc", "openjdk21", "libstdc++", "busybox", "gcompat"])
            run_chroot(["ln", "-sf", "/usr/lib/jvm/java-21-openjdk/bin/java", "/usr/bin/java"])
            run_chroot(["sh", "-c", "ln -sf /usr/lib/jvm/java-21-openjdk/lib/libjli.so /usr/lib/libjli.so"])
            run_chroot(["sh", "-c", "ln -sf /usr/lib/jvm/java-21-openjdk/lib/server/libjvm.so /usr/lib/libjvm.so"])
        except Exception as e:
            print(f"Fatal error: {e}")
            sys.exit(1)
        finally:
            for d in ["proc", "dev", "sys"]:
                subprocess.run(["umount", os.path.join(ROOTFS_DIR, d)], check=False)

    app_dir = os.path.join(ROOTFS_DIR, "app")
    os.makedirs(app_dir, exist_ok=True)
    src_jar = os.path.abspath("vessel-engine/target/vessel-engine-0.0.1-SNAPSHOT.jar")
    if os.path.exists(src_jar):
        shutil.copy(src_jar, os.path.join(app_dir, "vessel-engine.jar"))
        print(f"SUCCESS: Copied {src_jar} to {app_dir}")
    else:
        print(f"FATAL: Source JAR not found at {src_jar}")
        sys.exit(1)

if __name__ == "__main__":
    if os.getuid() != 0:
        print("Must be root.")
        sys.exit(1)
    provision_rootfs()