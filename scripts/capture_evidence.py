"""
Python script to interact with Chrome via DevTools Protocol (CDP) to capture screenshots:
1. 3x3 Grid
2. Preview Panel (click on a camera card)
3. Faces Gallery
4. Faces Table (toggle to table view)
5. Live Alerts feed with NIGHT_MOVEMENT
6. DevTools Issues collection
"""
import subprocess
import time
import json
import urllib.request
import websockets
import asyncio
import os
import base64

ARTIFACT_DIR = "/Users/devpachori/.gemini/antigravity-ide/brain/09d36237-2b9d-4598-8379-00e6d92b9ecc"

async def cdp_session():
    # 1. Launch headless Chrome with debugging port
    cmd = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "--headless=new",
        "--remote-debugging-port=9222",
        "--window-size=1400,900",
        "--no-sandbox",
        "--disable-gpu",
        "about:blank"
    ]
    proc = subprocess.Popen(cmd)
    time.sleep(2.0)

    try:
        # Get target websocket URL
        res = urllib.request.urlopen("http://localhost:9222/json/list")
        targets = json.loads(res.read().decode())
        ws_url = targets[0]["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url) as ws:
            req_id = 1
            issues = []

            async def send(method, params=None):
                nonlocal req_id
                req_id += 1
                msg = {"id": req_id, "method": method, "params": params or {}}
                await ws.send(json.dumps(msg))
                while True:
                    resp = json.loads(await ws.recv())
                    if "method" in resp and resp["method"] == "Audits.issueAdded":
                        issues.append(resp["params"]["issue"])
                    if resp.get("id") == req_id:
                        return resp.get("result", {})

            # Enable domains
            await send("Page.enable")
            await send("DOM.enable")
            await send("Runtime.enable")
            await send("Audits.enable")

            # ── 1. HOMEPAGE & 3x3 GRID ──────────────────────────────────────────
            print("Navigating to http://localhost:3000...")
            await send("Page.navigate", {"url": "http://localhost:3000"})
            await asyncio.sleep(4.0)

            # Screenshot 1: 3x3 Grid
            shot = await send("Page.captureScreenshot", {"format": "png"})
            with open(os.path.join(ARTIFACT_DIR, "shot_3x3_grid.png"), "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            print("Saved shot_3x3_grid.png")

            # Screenshot 2: Click camera card to open Preview Panel
            # Select first or second camera tile and click it
            await send("Runtime.evaluate", {
                "expression": """
                (function() {
                    const cards = document.querySelectorAll('.camera-card, .camera-tile');
                    if (cards.length > 0) {
                        cards[0].click();
                        return 'clicked ' + cards.length + ' cards';
                    }
                    return 'no cards';
                })()
                """
            })
            await asyncio.sleep(2.0)
            shot2 = await send("Page.captureScreenshot", {"format": "png"})
            with open(os.path.join(ARTIFACT_DIR, "shot_preview_panel.png"), "wb") as f:
                f.write(base64.b64decode(shot2["data"]))
            print("Saved shot_preview_panel.png")

            # ── 2. FACES GALLERY & TABLE ───────────────────────────────────────
            print("Navigating to http://localhost:3000/faces...")
            await send("Page.navigate", {"url": "http://localhost:3000/faces"})
            await asyncio.sleep(3.0)

            # Screenshot 3: Faces Gallery
            shot3 = await send("Page.captureScreenshot", {"format": "png"})
            with open(os.path.join(ARTIFACT_DIR, "shot_faces_gallery.png"), "wb") as f:
                f.write(base64.b64decode(shot3["data"]))
            print("Saved shot_faces_gallery.png")

            # Screenshot 4: Toggle to Faces Table View
            await send("Runtime.evaluate", {
                "expression": """
                (function() {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    const tableBtn = buttons.find(b => b.textContent.includes('Table') || b.title?.includes('Table'));
                    if (tableBtn) {
                        tableBtn.click();
                        return 'table btn clicked';
                    }
                    return 'table btn not found';
                })()
                """
            })
            await asyncio.sleep(2.0)
            shot4 = await send("Page.captureScreenshot", {"format": "png"})
            with open(os.path.join(ARTIFACT_DIR, "shot_faces_table.png"), "wb") as f:
                f.write(base64.b64decode(shot4["data"]))
            print("Saved shot_faces_table.png")

            # Write issues log
            with open(os.path.join(ARTIFACT_DIR, "devtools_issues.json"), "w") as f:
                json.dump(issues, f, indent=2)
            print(f"Collected {len(issues)} DevTools Issues: saved devtools_issues.json")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except Exception:
            proc.kill()

if __name__ == "__main__":
    asyncio.run(cdp_session())
