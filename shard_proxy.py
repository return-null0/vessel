import hashlib
import json
import time
import os
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
import pymysql

class ConsistentHashRing:
    def __init__(self, replicas=100):
        self.replicas = replicas
        self.ring = {}
        self.sorted_keys = []

    def _hash(self, key):
        return int(hashlib.sha256(key.encode('utf-8')).hexdigest(), 16)

    def add_node(self, node_name):
        for i in range(self.replicas):
            virtual_node_key = f"{node_name}:replica:{i}"
            hashed_key = self._hash(virtual_node_key)
            self.ring[hashed_key] = node_name
            self.sorted_keys.append(hashed_key)
        self.sorted_keys.sort()

    def remove_node(self, node_name):
        self.ring = {k: v for k, v in self.ring.items() if v != node_name}
        self.sorted_keys = sorted(self.ring.keys())

    def get_node(self, string_key):
        if not self.ring:
            return None
        hashed_key = self._hash(string_key)
        for node_hash in self.sorted_keys:
            if hashed_key <= node_hash:
                return self.ring[node_hash]
        return self.ring[self.sorted_keys[0]]

class VesselProxyRouter:
    def __init__(self):
        self.ring = ConsistentHashRing(replicas=50)
        self.connections = {}
        self.shard_ips = self._discover_shards()
        self.last_signal_time = 0.0
        self._connect_and_initialize()

    def _discover_shards(self):
        print("[Proxy] Scanning host network for Vessel shards...", flush=True)
        discovered = []
        time.sleep(2) 
        interfaces = os.listdir('/sys/class/net')
        for iface in interfaces:
            if iface.startswith('v-host'):
                shard_id = int(iface.replace('v-host', ''))
                ip = f"10.0.0.{shard_id + 1}"
                discovered.append((f"shard_{shard_id}", ip))
        print(f"[Proxy] Discovered {len(discovered)} active shards.", flush=True)
        return discovered

    def _wait_for_port(self, ip, port, timeout=30):
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.create_connection((ip, port), timeout=1):
                    return True
            except OSError:
                time.sleep(1)
        return False

    def _connect_and_initialize(self):
        for name, ip in self.shard_ips:
            print(f"[Proxy] Waiting for MariaDB to boot on {name} ({ip})...", flush=True)
            if not self._wait_for_port(ip, 3306):
                print(f"[Proxy] FATAL: Shard {name} failed to bind port 3306.", flush=True)
                continue

            connected = False
            for attempt in range(10):
                try:
                    conn = pymysql.connect(
                        host=ip, user='mysql', password='vesseladmin',
                        autocommit=True, connect_timeout=30,
                        read_timeout=60, write_timeout=60
                    )
                    self._setup_schema(conn)
                    self.connections[name] = conn
                    self.ring.add_node(name)
                    print(f"[Proxy] Successfully integrated {name} into hash ring.", flush=True)
                    connected = True
                    break
                except pymysql.MySQLError:
                    time.sleep(2)
            if not connected:
                print(f"[Proxy] FATAL: Could not authenticate with {name}.", flush=True)

    def _setup_schema(self, conn):
        with conn.cursor() as cursor:
            cursor.execute("CREATE DATABASE IF NOT EXISTS vessel_data")
            cursor.execute("USE vessel_data")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    id VARCHAR(255) PRIMARY KEY,
                    payload JSON
                )
            """)

    def generate_dashboard(self):
        
        dashboard = {
            "cluster_status": "Healthy",
            "total_records": 0,
            "total_memory_mb": 0.0,
            "shards": []
        }
        current_time = time.time()
        send_signals = (current_time - self.last_signal_time) > 30.0
        if send_signals:
            self.last_signal_time = current_time

        for name, ip in self.shard_ips:
            shard_id = name.split('_')[1]
            rootfs = f"/tmp/vessel-root_{shard_id}"
            telemetry_file = f"{rootfs}/telemetry.json"
            
            supervisor_pid_file = f"{rootfs}/supervisor.pid"
            
            node_stats = {
                "name": name, 
                "ip": ip, 
                "status": "offline", 
                "records": 0,
                "memory_mb": 0.0,
                "cpu_sec": 0.0,
                "threads": 0
            }
            
            if name in self.connections:
                try:
                    self.connections[name].ping(reconnect=True)
                    with self.connections[name].cursor() as cursor:
                        cursor.execute("USE vessel_data")
                        cursor.execute("SELECT COUNT(*) FROM records")
                        node_stats["records"] = cursor.fetchone()[0]
                        dashboard["total_records"] += node_stats["records"]
                        node_stats["status"] = "online"
                except Exception:
                    node_stats["status"] = "db_error"

            if os.path.exists(supervisor_pid_file) and send_signals:
                try:
                    with open(supervisor_pid_file, "r") as f:
                        host_pid = int(f.read().strip())
                        os.kill(host_pid, 10) 
                        time.sleep(0.15) 
                except Exception:
                    pass
                    
            if os.path.exists(telemetry_file):
                try:
                    with open(telemetry_file, "r") as tf:
                        t_data = json.load(tf)
                        node_stats["memory_mb"] = t_data.get("memory_mb", 0.0)
                        node_stats["cpu_sec"] = t_data.get("cpu_sec", 0.0)
                        node_stats["threads"] = t_data.get("total_threads", 0)
                        
                        if node_stats["status"] == "online":
                            node_stats["status"] = "active"
                            
                        dashboard["total_memory_mb"] += node_stats["memory_mb"]
                except Exception:
                    pass
            
            dashboard["shards"].append(node_stats)
            
        dashboard["total_memory_mb"] = round(dashboard["total_memory_mb"], 2)
        return dashboard

    def insert_record(self, record_id, payload):
        target_shard = self.ring.get_node(record_id)
        if not target_shard: return None
        conn = self.connections.get(target_shard)
        if not conn: return "failed_retry_needed"
        try:
            conn.ping(reconnect=True)
            with conn.cursor() as cursor:
                cursor.execute("USE vessel_data")
                cursor.execute("REPLACE INTO records (id, payload) VALUES (%s, %s)", (record_id, json.dumps(payload)))
            return target_shard
        except pymysql.MySQLError:
            self.generate_dashboard()
            return "failed_retry_needed"

    def get_record(self, record_id):
        target_shard = self.ring.get_node(record_id)
        if not target_shard: return None, None
        conn = self.connections.get(target_shard)
        if not conn: return target_shard, None
        try:
            conn.ping(reconnect=True)
            with conn.cursor() as cursor:
                cursor.execute("USE vessel_data")
                cursor.execute("SELECT payload FROM records WHERE id = %s", (record_id,))
                result = cursor.fetchone()
                if result: return target_shard, json.loads(result[0])
                return target_shard, None
        except pymysql.MySQLError:
            self.generate_dashboard()
            return target_shard, None

    def reconstruct_database(self):
        unified_database = {}
        for name, conn in self.connections.items():
            try:
                conn.ping(reconnect=True)
                with conn.cursor() as cursor:
                    cursor.execute("USE vessel_data")
                    cursor.execute("SELECT id, payload FROM records")
                    rows = cursor.fetchall()
                    for row in rows:
                        unified_database[row[0]] = {"shard": name, "payload": json.loads(row[1])}
            except Exception as e:
                print(f"[Proxy] Error reading from {name}: {e}", flush=True)
        return unified_database

class ProxyHTTPHandler(BaseHTTPRequestHandler):
    def _send_response(self, code, data):
        try:
            self.send_response(code)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if self.path == '/insert':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            body = json.loads(post_data)
            target = router.insert_record(body.get('id'), body.get('payload'))
            
            if not target: self._send_response(503, {"error": "Cluster offline. No active shards in ring."})
            elif target == "failed_retry_needed": self._send_response(502, {"error": "Target shard failed. Retry."})
            else: self._send_response(200, {"status": "success", "routed_to": target})
        else:
            self._send_response(404, {"error": "Endpoint not found"})

    def do_GET(self):
        if self.path == '/' or self.path == '/dashboard':
            try:
                with open('dashboard.html', 'r', encoding='utf-8') as f:
                    html_content = f.read()
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(html_content.encode('utf-8'))
            except FileNotFoundError:
                self.send_response(404); self.end_headers()
        elif self.path == '/api/status':
            status_data = router.generate_dashboard()
            self._send_response(200, status_data)
        elif self.path == '/api/reconstruct':
            self._send_response(200, {"status": "success", "data": router.reconstruct_database()})
        elif self.path.startswith('/retrieve/'):
            record_id = self.path.split('/')[-1]
            target, payload = router.get_record(record_id)
            if not target: self._send_response(503, {"error": "Cluster offline."})
            elif payload: self._send_response(200, {"status": "success", "routed_to": target, "data": payload})
            else: self._send_response(404, {"error": "Record not found", "routed_to": target})
        elif self.path == '/pics/favicon.ico':
            try:
                with open('.' + self.path, 'rb') as file:
                    content = file.read()
                
                self.send_response(200)
                self.send_header('Content-Type', 'image/x-icon')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_error(404, "Favicon not found")
                
        else:
            self._send_response(404, {"error": "Endpoint not found"})

if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir: os.chdir(script_dir)

    router = VesselProxyRouter()
    server_address = ('0.0.0.0', 8080)
    httpd = HTTPServer(server_address, ProxyHTTPHandler)
    print("\n[Proxy] Vessel Sharding Proxy active on port 8080.", flush=True)
    try: httpd.serve_forever()
    except KeyboardInterrupt: print("[Proxy] Shutting down.")