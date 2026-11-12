"""One-page DG EDGE public UI capability diagnostic, not a bulk extractor.

Observes first-party request *structure* and visible leaderboard controls.
Never captures player records, response bodies, cookies, authorization values,
or attempts hidden endpoints. Limited to a single public event page.
"""
import asyncio
import json
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright

EVENT = "https://www.dg-edge.com/events/dailies/week-46-2026-race-c-michelin-raceway-road-atlanta/696"

async def main():
    responses = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 1000}, locale="en-US")

        def handle_response(response):
            parsed = urlparse(response.url)
            if not parsed.hostname or not parsed.hostname.endswith("dg-edge.com"):
                return
            path = parsed.path
            if any(x in path.lower() for x in ("auth", "login", "token", "session")):
                return
            item = {
                "host": parsed.hostname, "path": path[:160],
                "status": response.status, "type": response.request.resource_type,
                "query_keys": sorted(parse_qs(parsed.query).keys()),
            }
            if len(responses) < 90:
                responses.append(item)

        page.on("response", handle_response)
        try:
            initial = await page.goto(EVENT, wait_until="domcontentloaded", timeout=45000)
            print("DG_PAGE_STATUS:", initial.status if initial else None, flush=True)
            await page.wait_for_timeout(6500)
            print("DG_TITLE:", (await page.title())[:140], flush=True)
            text = await page.locator("body").inner_text()
            print("DG_MARKERS:", json.dumps({
                "filter_dr": "DR" in text,
                "total_players": "Total players" in text or "Drivers" in text,
                "leaderboard": "Leaderboard" in text or "leaderboard" in text,
                "pagination": "Next" in text or "Previous" in text,
            }), flush=True)
            print("DG_UI:", json.dumps(await page.evaluate("""() => ({
                tables: document.querySelectorAll('table').length,
                tbodyRows: document.querySelectorAll('table tbody tr').length,
                selects: Array.from(document.querySelectorAll('select')).map(s => ({
                    name: s.name, id: s.id,
                    options: Array.from(s.options).slice(0, 18).map(o => o.textContent.trim().slice(0, 40))
                })).slice(0, 18),
                buttons: Array.from(document.querySelectorAll('button')).map(b => ({
                    text:(b.innerText || '').trim().slice(0, 45),
                    aria:b.getAttribute('aria-label')
                })).filter(b => /filter|next|prev|100|page|dr/i.test((b.text||'')+' '+(b.aria||''))).slice(0, 25),
                lists: document.querySelectorAll('[role=listbox]').length
            })""")), flush=True)
            # Read-only assessment of network request structure.
            seen = set()
            interesting = []
            for response in responses:
                if response["type"] in ("xhr", "fetch", "document"):
                    key = (response["host"], response["path"], response["status"], response["type"], tuple(response["query_keys"]))
                    if key not in seen:
                        interesting.append(response)
                        seen.add(key)
            print("DG_REQUEST_PATTERNS:", json.dumps(interesting[:25]), flush=True)
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
