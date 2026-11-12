"""Observe GTSH's public leaderboard through Chromium, without credentials.

Read-only test: navigates to the public index and currently running Race C,
observes normal front-end HTTP requests, and logs only status/type/error code.
Does not log cookies, headers, full URLs, payloads, personal information,
or attempt to circumvent any server access restrictions.
"""
import asyncio
import json
from urllib.parse import urlparse

from playwright.async_api import async_playwright


def safe_event(response):
    url = urlparse(response.url)
    if url.hostname not in {"gtsh-rank.com", "www.gtsh-rank.com"}:
        return False
    if "/daily/leaderboard" not in url.path:
        return False
    return True


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="en-US", timezone_id="America/Sao_Paulo")
        page = await context.new_page()
        observed = []

        async def on_response(response):
            if not safe_event(response):
                return
            url = urlparse(response.url)
            from urllib.parse import parse_qs
            query = parse_qs(url.query)
            kind = ("page_data" if "page_data" in query
                    else "update" if "update" in query else "html")
            status = response.status
            item = {"type": kind, "status": status, "path": url.path}
            if status in (401, 403) and kind != "html":
                try:
                    data = await response.json()
                    if isinstance(data, dict):
                        item["error_code"] = str(data.get("code", ""))[:80]
                        item["error"] = str(data.get("error", ""))[:100]
                except Exception:
                    pass
            if kind == "page_data":
                from urllib.parse import parse_qs
                item["query_parameter_names"] = sorted(parse_qs(url.query).keys())
                # Log only safe aggregate counts and structural keys. No drivers.
                if status == 200:
                    try:
                        payload = await response.json()
                        if isinstance(payload, dict):
                            item["json_field_names"] = sorted(payload.keys())[:25]
                            item["data_kind"] = type(payload.get("data")).__name__
                            if isinstance(payload.get("data"), (str, list, dict)):
                                item["data_length"] = len(payload["data"])
                            item["format_kind"] = type(payload.get("format")).__name__
                            item["usage_kind"] = type(payload.get("usage")).__name__
                            if isinstance(payload.get("usage"), dict):
                                item["usage_keys"] = sorted(payload["usage"].keys())[:20]
                            item["nonce_present"] = bool(payload.get("nonce"))
                            for field in ("total", "total_drivers", "totalDrivers", "count", "recordsTotal"):
                                if isinstance(payload.get(field), (int, float)):
                                    item["declared_total"] = int(payload[field])
                                    break
                            for field in ("board", "ranking", "data", "entries", "results", "drivers"):
                                if isinstance(payload.get(field), list):
                                    item["returned_count"] = len(payload[field])
                                    break
                        elif isinstance(payload, list):
                            item["returned_count"] = len(payload)
                    except Exception:
                        item["json_parse"] = "failed"
                # Request header names only, never values or cookie/token data.
                item["request_header_names"] = sorted(response.request.headers.keys())
            observed.append(item)
            print("BROWSER_RESPONSE: " + json.dumps(item, ensure_ascii=False), flush=True)

        page.on("response", on_response)
        try:
            index = await page.goto("https://gtsh-rank.com/daily/", wait_until="domcontentloaded", timeout=45000)
            print(f"BROWSER_INDEX: status={index.status if index else 'no-response'}", flush=True)
            link = page.locator('a[href*="/daily/leaderboard?event="], a[href*="/daily/leaderboard/?event="]')
            count = await link.count()
            print(f"BROWSER_INDEX: leaderboard_links={count}", flush=True)
            # Use same provenance as the production detector to avoid another event.
            import requests
            from datetime import datetime
            from zoneinfo import ZoneInfo
            from bs4 import BeautifulSoup
            from test_race_detector import find_current_race_c
            selected = find_current_race_c(BeautifulSoup(await page.content(), "html.parser"),
                                           datetime.now(ZoneInfo("America/Sao_Paulo")))
            print("BROWSER_EVENT: current_week_C_selected=True", flush=True)
            response = await page.goto(selected["url"], wait_until="domcontentloaded", timeout=45000)
            print(f"BROWSER_LEADERBOARD_HTML: status={response.status if response else 'no-response'}", flush=True)
            await page.wait_for_timeout(10000)
            # Pagination control discovery: classes and labels only,
            # never driver names or row contents.
            pagination_selectors = (
                'button[aria-label*="Next"]',
                '[class*="pagination"]',
                '[class*="pager"]',
                'a[rel="next"]',
                'button[data-page]',
            )
            for selector in pagination_selectors:
                print(f"BROWSER_UI: {selector!r} count={await page.locator(selector).count()}", flush=True)
            # Native browser requests only. No custom headers, tokens or hidden endpoints.
            # Browser UI pagination is clicked only if an unambiguous standard next button exists.
            next_buttons = page.get_by_role("button", name="Next", exact=True)
            if await next_buttons.count() == 1 and await next_buttons.first.is_enabled():
                await next_buttons.first.click(timeout=3000)
                print("BROWSER_CLICKED_NATIVE_NEXT: True", flush=True)
                await page.wait_for_timeout(4000)
            else:
                print("BROWSER_CLICKED_NATIVE_NEXT: False", flush=True)
            api = [r for r in observed if r["type"] in {"page_data", "update"}]
            print(f"BROWSER_SUMMARY: api_requests={len(api)} ok={sum(1 for x in api if x['status']==200)} forbidden={sum(1 for x in api if x['status'] in (401,403))}", flush=True)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
