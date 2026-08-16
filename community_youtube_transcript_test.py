"""
GT7 YouTube Transcript Test
===========================

Teste isolado do serviço youtube-transcript.ai.

Objetivo:
- testar a obtenção da transcrição do vídeo de estratégia da Digit Racing;
- não alterar nenhum arquivo do pipeline principal;
- salvar a resposta para inspeção posterior.

Video:
Digit Racing
GT7 | Grand Valley - New Week Of Daily Racing! | Live
https://www.youtube.com/watch?v=O-AfZNXuGBg
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


VIDEO_ID = "O-AfZNXuGBg"
CHANNEL = "Digit Racing"
ROLE = "STRATEGY"

API_URL = (
    f"https://youtube-transcript.ai/transcript/{VIDEO_ID}.txt"
    "?lang=en"
)

OUTPUT_DIR = Path("data/community_youtube_transcript_test")
OUTPUT_TXT = OUTPUT_DIR / f"{VIDEO_ID}_digit_racing.txt"
OUTPUT_JSON = OUTPUT_DIR / f"{VIDEO_ID}_digit_racing.json"

TIMEOUT = 60


def separator(char: str = "=", width: int = 88) -> None:
    print(char * width)


def save_json(data: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with OUTPUT_JSON.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
        )


def main() -> int:
    separator()
    print("GT7 YOUTUBE TRANSCRIPT TEST V1")
    separator()

    print(f"Channel          : {CHANNEL}")
    print(f"Role             : {ROLE}")
    print(f"Video ID         : {VIDEO_ID}")
    print(f"YouTube URL      : https://www.youtube.com/watch?v={VIDEO_ID}")
    print("Provider         : youtube-transcript.ai")
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0 Safari/537.36"
        ),
        "Accept": "text/markdown,text/plain;q=0.9,*/*;q=0.8",
    }

    print("REQUEST")
    separator("-")

    print("Requesting transcript...")
    print(f"Endpoint         : {API_URL}")
    print()

    try:
        response = requests.get(
            API_URL,
            headers=headers,
            timeout=TIMEOUT,
        )

    except requests.Timeout:
        print("Result           : TIMEOUT")

        save_json(
            {
                "video_id": VIDEO_ID,
                "channel": CHANNEL,
                "role": ROLE,
                "provider": "youtube-transcript.ai",
                "status": "TIMEOUT",
                "tested_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        return 1

    except requests.RequestException as exc:
        print("Result           : REQUEST_ERROR")
        print(f"Error            : {exc}")

        save_json(
            {
                "video_id": VIDEO_ID,
                "channel": CHANNEL,
                "role": ROLE,
                "provider": "youtube-transcript.ai",
                "status": "REQUEST_ERROR",
                "error": str(exc),
                "tested_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        return 1

    print(f"HTTP status      : {response.status_code}")
    print(f"Content-Type     : {response.headers.get('content-type', 'UNKNOWN')}")
    print(f"Response bytes   : {len(response.content):,}")

    text = response.text.strip()

    print(f"Response chars   : {len(text):,}")
    print()

    if response.status_code != 200:
        print("Result           : HTTP_ERROR")
        print()
        print("RESPONSE PREVIEW")
        separator("-")
        print(text[:2000])

        save_json(
            {
                "video_id": VIDEO_ID,
                "channel": CHANNEL,
                "role": ROLE,
                "provider": "youtube-transcript.ai",
                "status": "HTTP_ERROR",
                "http_status": response.status_code,
                "response_preview": text[:5000],
                "tested_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        return 1

    if not text:
        print("Result           : EMPTY_RESPONSE")

        save_json(
            {
                "video_id": VIDEO_ID,
                "channel": CHANNEL,
                "role": ROLE,
                "provider": "youtube-transcript.ai",
                "status": "EMPTY_RESPONSE",
                "http_status": response.status_code,
                "tested_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        return 1

    lower_text = text.lower()

    error_indicators = (
        "transcript unavailable",
        "video unavailable",
        "captions unavailable",
        "no transcript",
        "error fetching",
        "failed to fetch",
    )

    detected_errors = [
        indicator
        for indicator in error_indicators
        if indicator in lower_text
    ]

    if detected_errors:
        print("Result           : PROVIDER_ERROR_RESPONSE")
        print(f"Indicators       : {', '.join(detected_errors)}")
        print()
        print("RESPONSE PREVIEW")
        separator("-")
        print(text[:3000])

        save_json(
            {
                "video_id": VIDEO_ID,
                "channel": CHANNEL,
                "role": ROLE,
                "provider": "youtube-transcript.ai",
                "status": "PROVIDER_ERROR_RESPONSE",
                "http_status": response.status_code,
                "indicators": detected_errors,
                "response_preview": text[:5000],
                "tested_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        return 1

    word_count = len(text.split())

    OUTPUT_TXT.write_text(
        text,
        encoding="utf-8",
    )

    metadata = {
        "video_id": VIDEO_ID,
        "youtube_url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "channel": CHANNEL,
        "role": ROLE,
        "provider": "youtube-transcript.ai",
        "status": "AVAILABLE",
        "http_status": response.status_code,
        "characters": len(text),
        "words": word_count,
        "transcript_file": str(OUTPUT_TXT),
        "tested_at": datetime.now(timezone.utc).isoformat(),
    }

    save_json(metadata)

    print("RESULT")
    separator("-")

    print("Transcript       : YES")
    print(f"Words            : {word_count:,}")
    print(f"Characters       : {len(text):,}")
    print(f"Saved transcript : {OUTPUT_TXT}")
    print(f"Saved metadata   : {OUTPUT_JSON}")
    print()

    print("TRANSCRIPT PREVIEW")
    separator("-")

    preview_length = 4000
    print(text[:preview_length])

    if len(text) > preview_length:
        print()
        print("[... transcript truncated in console ...]")

    print()
    separator()
    print("TEST SUCCESSFUL")
    separator()

    return 0


if __name__ == "__main__":
    sys.exit(main())