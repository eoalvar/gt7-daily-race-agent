"""Check ordinary read-only HTTP access to public DG EDGE pages (no bypass)."""
import urllib.error
import urllib.request
from urllib.parse import urlsplit

URLS = [
    "https://www.dg-edge.com/",
    "https://www.dg-edge.com/p/faq",
    "https://www.dg-edge.com/events/dailies/week-46-2026-race-c-michelin-raceway-road-atlanta/696",
]
for url in URLS:
    try:
        response = urllib.request.urlopen(urllib.request.Request(url), timeout=20)
        with response:
            print("HTTP_PROBE:", urlsplit(url).path, response.status,
                  response.headers.get("content-type", "").split(";")[0], flush=True)
    except urllib.error.HTTPError as err:
        print("HTTP_PROBE:", urlsplit(url).path, err.code,
              err.headers.get("content-type", "").split(";")[0], flush=True)
    except Exception as err:
        print("HTTP_PROBE:", urlsplit(url).path, type(err).__name__, flush=True)
