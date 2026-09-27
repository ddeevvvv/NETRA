import asyncio
import os
import shutil
from playwright.async_api import async_playwright

ARTIFACT_DIR = "/Users/devpachori/.gemini/antigravity-ide/brain/2bdc095e-258f-4069-a067-99471c305c2a"

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            headless=True
        )
        page = await browser.new_page(viewport={'width': 1440, 'height': 900})

        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))

        print("Navigating to http://127.0.0.1:3000 ...")
        await page.goto('http://127.0.0.1:3000', wait_until='domcontentloaded')
        await page.wait_for_timeout(1500)

        # 1. Dashboard View
        print("1. Capturing Dashboard View...")
        dash_path = os.path.join(ARTIFACT_DIR, "artifact_dashboard_view.png")
        await page.screenshot(path=dash_path)
        print(f"Saved {dash_path}")

        # 2. Site Map View screenshot
        print("2. Navigating to Site Map...")
        site_map_btn = page.locator("button:has-text('Site Map')")
        if await site_map_btn.count() > 0:
            await site_map_btn.first.click()
            await page.wait_for_timeout(1200)
            
            # Click on first pin node to open popover / detail drawer
            pins = page.locator(".schematic-pin-node")
            if await pins.count() > 0:
                await pins.first.click()
                await page.wait_for_timeout(500)

        sitemap_path = os.path.join(ARTIFACT_DIR, "artifact_sitemap_view.png")
        await page.screenshot(path=sitemap_path)
        print(f"Saved {sitemap_path}")

        # 3. Investigate -> Incident Summaries View
        print("3. Navigating to Investigate -> Incident Summaries...")
        inv_btn = page.locator("button:has-text('Investigate')")
        if await inv_btn.count() > 0:
            await inv_btn.first.click()
            await page.wait_for_timeout(1000)

            sum_tab = page.locator("button:has-text('Incident Summaries')")
            if await sum_tab.count() > 0:
                await sum_tab.first.click()
                await page.wait_for_timeout(1500)

        summaries_path = os.path.join(ARTIFACT_DIR, "artifact_incident_summaries_view.png")
        await page.screenshot(path=summaries_path)
        print(f"Saved {summaries_path}")

        # 4. Investigate -> Event Log Search View with executed query
        print("4. Navigating to Investigate -> Event Log Search...")
        event_tab = page.locator("button:has-text('Event Log Search')")
        if await event_tab.count() > 0:
            await event_tab.first.click()
            await page.wait_for_timeout(1000)

            # Click Search button to populate results table
            search_btn = page.locator(".search-btn")
            if await search_btn.count() > 0:
                await search_btn.first.click()
                await page.wait_for_timeout(2000)

            # Scroll table container down to verify sticky header and zebra striping
            table_wrap = page.locator(".events-table-wrap")
            if await table_wrap.count() > 0:
                await table_wrap.first.evaluate("el => el.scrollTop = 100")
                await page.wait_for_timeout(500)

        events_path = os.path.join(ARTIFACT_DIR, "artifact_event_log_search_view.png")
        await page.screenshot(path=events_path)
        print(f"Saved {events_path}")

        # 5. Investigate -> Track Vehicle Sightings View
        print("5. Navigating to Investigate -> Track Vehicle Sightings...")
        track_tab = page.locator("button:has-text('Track Vehicle Sightings')")
        if await track_tab.count() > 0:
            await track_tab.first.click()
            await page.wait_for_timeout(1000)

            # Click a quick tag button or fill plate input
            quick_tag = page.locator(".quick-tag-btn")
            if await quick_tag.count() > 0:
                await quick_tag.first.click()
                await page.wait_for_timeout(500)

            track_submit = page.locator(".btn-track-submit")
            if await track_submit.count() > 0 and await track_submit.first.is_enabled():
                await track_submit.first.click()
                await page.wait_for_timeout(1200)

        track_path = os.path.join(ARTIFACT_DIR, "artifact_track_vehicle_view.png")
        await page.screenshot(path=track_path)
        print(f"Saved {track_path}")

        # Console Audit (Playwright page.on("console") listener)
        print("\n" + "=" * 60)
        print("PLAYWRIGHT CONSOLE AUDIT SUMMARY")
        print("=" * 60)
        errors = [m for m in console_logs if "error" in m.lower()]
        warnings = [m for m in console_logs if "warn" in m.lower()]
        print(f"Total Console Messages: {len(console_logs)}")
        print(f"Console Errors Count:   {len(errors)}")
        print(f"Console Warnings Count: {len(warnings)}")
        print("Note: Chrome DevTools 'Issues' tab (CDP Audits domain) is not monitored by this listener.")
        if errors:
            for err in errors:
                print(f"  ❌ {err}")
        else:
            print("  ✓ CLEAN CONSOLE — 0 Errors reported.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())

