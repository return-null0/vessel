import urllib.request
import json
import random
import time

PROXY_URL = "http://localhost:8080/insert"

def send_request(record_id, payload_data):
    data = json.dumps({"id": record_id, "payload": payload_data}).encode('utf-8')
    req = urllib.request.Request(PROXY_URL, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode())
            print(f"Inserted {record_id} -> {res.get('routed_to')}")
    except Exception as e:
        print(f"Failed to insert {record_id}: {e}")

print("Initializing cluster population sequence...\n")

departments = ["engineering", "sales", "hr", "operations"]
locations = ["ny-pomona", "ny-brooklyn", "wa-seattle", "pl-warsaw"]

for i in range(1, 101):
    record_id = f"usr_{i:03d}"
    payload = {
        "type": "user_profile",
        "active": random.choice([True, True, False]),
        "department": random.choice(departments),
        "location": random.choice(locations),
        "access_level": random.randint(1, 5)
    }
    send_request(record_id, payload)

statuses = ["online", "online", "online", "degraded", "offline"]

for i in range(1, 101):
    record_id = f"dev_sensor_{i:03d}"
    payload = {
        "type": "telemetry",
        "status": random.choice(statuses),
        "temperature_c": round(random.uniform(20.0, 85.5), 2),
        "uptime_hours": random.randint(10, 5000),
        "firmware": f"v2.{random.randint(0,4)}.{random.randint(0,9)}"
    }
    send_request(record_id, payload)

for i in range(1, 51):
    record_id = f"sys_conf_{i:03d}"
    payload = {
        "type": "configuration",
        "feature_flags": {
            "enable_beta": random.choice([True, False]),
            "max_connections": random.choice([100, 500, 1000]),
            "maintenance_mode": False
        },
        "allocated_memory_mb": random.choice([256, 512, 1024, 2048])
    }
    send_request(record_id, payload)

print("\nCluster population complete. You can now test the reconstruction dashboard.")