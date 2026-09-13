import argparse
import asyncio
import json
import sys
from datetime import datetime
import websockets

async def listen_alerts(uri: str):
    print(f"[WS] Connecting to IBVAP WebSocket at {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("[WS] Connected to real-time alert stream! Listening for events...\n")
            sys.stdout.flush()
            async for message in websocket:
                try:
                    event = json.loads(message)
                    event_id = event.get("id", "N/A")
                    cam_id = event.get("camera_id", "N/A")
                    event_type = event.get("type", "N/A")
                    severity = event.get("severity", "N/A")
                    track_id = event.get("track_id", "N/A")
                    confidence = event.get("confidence", "N/A")
                    meta = event.get("metadata", {})

                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] ALERT RECEIVED | "
                        f"ID: {event_id} | Type: {event_type} | Severity: {severity} | "
                        f"Camera: {cam_id} | Track: {track_id} | Conf: {confidence} | Meta: {meta}"
                    )
                    sys.stdout.flush()
                except json.JSONDecodeError:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Raw Message: {message}")
                    sys.stdout.flush()
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[WS] Connection closed: {e}")
    except Exception as e:
        print(f"[WS] Error: {e}")

def main():
    parser = argparse.ArgumentParser(description="IBVAP WebSocket Test Client")
    parser.add_argument("--url", default="ws://localhost:8000/ws/alerts", help="WebSocket URL for IBVAP backend alerts")
    args = parser.parse_args()

    try:
        asyncio.run(listen_alerts(args.url))
    except KeyboardInterrupt:
        print("\n[WS] Client stopped by user.")
        sys.exit(0)

if __name__ == "__main__":
    main()
