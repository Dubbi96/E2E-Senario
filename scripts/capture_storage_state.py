"""
Capture Playwright storageState after a manual login (e.g., Apple/Kakao/Naver).

Why:
- Apple login often triggers popup/2FA, which is not reliable in headless CI.
- Instead, login once in a headed browser and save storageState (cookies + localStorage).
- Then run headless tests with E2E_STORAGE_STATE_PATH or E2E_STORAGE_STATE_B64.

Usage:
  python3 scripts/capture_storage_state.py --out /abs/path/to/storage_state.json
  python3 scripts/capture_storage_state.py --url https://hogak.live/login_t --out ./storage_state.json
"""

from __future__ import annotations

import argparse
import os
from playwright.sync_api import sync_playwright


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://hogak.live/login_t", help="Start URL")
    ap.add_argument("--out", required=True, help="Output path for storage_state.json")
    ap.add_argument("--headless", action="store_true", help="Run headless (not recommended for Apple login)")
    args = ap.parse_args()

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=bool(args.headless))
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded")

        print("\n[storageState 캡처 안내]")
        print("- 열린 브라우저에서 로그인(Apple/Kakao/Naver/Google 등)을 완료하세요.")
        print("- 로그인 완료 후 엔터를 누르면 storageState를 저장합니다.")
        input("ENTER to save storageState > ")

        context.storage_state(path=out_path)
        print(f"Saved storageState: {out_path}")
        try:
            context.close()
        except Exception:
            pass
        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


