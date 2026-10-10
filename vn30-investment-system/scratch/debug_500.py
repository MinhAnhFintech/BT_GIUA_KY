import sys, os
sys.path.insert(0, r"c:\Users\ADMIN\Downloads\Bt giữa kỳ\vn30-investment-system")
os.chdir(r"c:\Users\ADMIN\Downloads\Bt giữa kỳ\vn30-investment-system")

from fastapi.testclient import TestClient
from backend.app.api.main import app

client = TestClient(app)

print("--- HEALTH ---")
try:
    r = client.get("/api/health")
    print(r.status_code)
    print(r.json())
except Exception as e:
    import traceback
    traceback.print_exc()

print("--- UNIVERSE ---")
try:
    r = client.get("/api/universe?date=2026-10-09")
    print(r.status_code)
    print(r.json())
except Exception as e:
    import traceback
    traceback.print_exc()

