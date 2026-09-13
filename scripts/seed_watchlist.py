import sys
import requests

ENTRIES = [
    {
        "type": "PLATE",
        "reference_value": "KA05NB4912",
        "list_type": "BLACKLIST",
        "added_by": "Officer-Singh",
        "notes": "Stolen White Scorpio — BOLO #1042"
    },
    {
        "type": "PLATE",
        "reference_value": "DL01AB1234",
        "list_type": "BLACKLIST",
        "added_by": "HQ-Intel",
        "notes": "Suspect Vehicle — Border Sector 3 Alert"
    },
    {
        "type": "PLATE",
        "reference_value": "MH12DE5678",
        "list_type": "BLACKLIST",
        "added_by": "Customs-Narcotics",
        "notes": "Narcotics Smuggling Watchlist — Pune Zone"
    },
    {
        "type": "PLATE",
        "reference_value": "HR26DQ5551",
        "list_type": "WHITELIST",
        "added_by": "Admin",
        "notes": "Authorized Border Patrol Escort Unit"
    }
]

def seed_watchlist(base_url="http://localhost:8000"):
    endpoint = f"{base_url.rstrip('/')}/api/v1/watchlist"
    print(f"[SEED] Seeding watchlist entries at {endpoint}...")

    success_count = 0
    for entry in ENTRIES:
        try:
            resp = requests.post(endpoint, json=entry, timeout=5)
            if resp.status_code == 201:
                data = resp.json()
                print(f"[SUCCESS] Added {data['list_type']} {data['type']}: '{data['reference_value']}' (ID: {data['id']})")
                success_count += 1
            elif resp.status_code == 400 and "already exists" in resp.text:
                print(f"[INFO] Entry '{entry['reference_value']}' ({entry['list_type']}) already exists in DB.")
            else:
                print(f"[WARNING] Failed to add '{entry['reference_value']}': {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"[ERROR] Could not connect to {endpoint}: {e}")

    print(f"[SEED] Completed. Added {success_count} new entries.\n")

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    seed_watchlist(url)
