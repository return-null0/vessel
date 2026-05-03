import ctypes
import os

libc = ctypes.CDLL("libc.so.6", use_errno=True)
SIGSET_SIZE = 128 

def signal_watcher_callback(arg):
    sig_set = (ctypes.c_char * SIGSET_SIZE)()
    libc.sigemptyset(ctypes.byref(sig_set))
    libc.sigaddset(ctypes.byref(sig_set), 10) 

    print("[Thread] Signal Watcher PARKED. Waiting for SIGUSR1 (10)...", flush=True)
    
    sig_received = ctypes.c_int(0)
    while True:
        res = libc.sigwait(ctypes.byref(sig_set), ctypes.byref(sig_received))
        
        if res == 0 and sig_received.value == 10:
            print("\r\n[Thread] EVENT: SIGUSR1 trapped by background watcher!", flush=True)
            print("[Thread] Resolving dynamic cgroup path...", flush=True)
            
            try:
                # 1. Dynamically read the container's cgroup location
                with open("/proc/1/cgroup", "r") as f:
                    cgroup_suffix = f.read().strip().split("::")[1]
                
                # 2. Construct the absolute path
                cgroup_path = f"/sys/fs/cgroup{cgroup_suffix}"
                print(f"[Thread] Target Path: {cgroup_path}", flush=True)
                
                # 3. Read Memory Telemetry
                with open(f"{cgroup_path}/memory.current", "r") as f:
                    mem_bytes = int(f.read().strip())
                    mem_mb = mem_bytes / (1024 * 1024)
                    print(f"  -> RAM Usage: {mem_mb:.2f} MB", flush=True)
                
                # 4. Read CPU Telemetry
                with open(f"{cgroup_path}/cpu.stat", "r") as f:
                    lines = f.readlines()
                    for line in lines:
                        if line.startswith("usage_usec"):
                            cpu_usec = int(line.split()[1])
                            cpu_sec = cpu_usec / 1_000_000
                            print(f"  -> CPU Time:  {cpu_sec:.4f} Seconds", flush=True)
                            break

                # 4. Read Execution Telemetry
                #this one includes threads!
                with open(f"{cgroup_path}/pids.current", "r") as f:
                    total_execution_contexts = int(f.read().strip())

                with open(f"{cgroup_path}/cgroup.procs", "r") as f:
                    pids = [int(line.strip()) for line in f.readlines() if line.strip()]
                    local_pids = [pid for pid in pids if pid > 0]
                    ghost_count = pids.count(0)
                    
                    print(f"  -> Total Threads/Tasks: {total_execution_contexts}", flush=True)
                    print(f"  -> PID Topology: {len(pids)} Processes", flush=True)
                    print(f"       Local Processes: {len(local_pids)} {local_pids}", flush=True)
                    print(f"       Ghost Processes: {ghost_count} (Invisible host scope)", flush=True)

                    
            except FileNotFoundError as e:
                print(f"  -> [Error] Telemetry file missing: {e}")
            except Exception as e:
                print(f"  -> [Error] Telemetry failure: {e}")
                
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
        print(f"[Vessel Init] Signal Watcher Thread {thread_id.value} detached.")
    else:
        print(f"[Vessel Init] Thread failed: {os.strerror(res)}")
