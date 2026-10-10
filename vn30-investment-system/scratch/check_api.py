import httpx
import json

base_url = "http://127.0.0.1:8000/api"

def check():
    try:
        # 1. Health
        r = httpx.get(f"{base_url}/health")
        print("Health:", r.status_code, r.text)

        # 2. Universe
        r = httpx.get(f"{base_url}/universe?date=2026-10-09")
        print("Universe:", r.status_code, r.text[:200])

        # 3. Try to get ranking to see if it fails
        r = httpx.get(f"{base_url}/ranking?as_of=2026-10-09")
        print("Ranking:", r.status_code, r.text[:200])

    except Exception as e:
        print("Error:", e)

check()

