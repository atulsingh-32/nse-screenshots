#!/usr/bin/env python3
"""
NSE Option Chain Screenshot Tool
Runs Mon-Sat, 9:30 AM - 3:30 PM IST
"""

import os
import sys
import time
import argparse
import warnings
from datetime import datetime, time as dtime, timedelta

warnings.filterwarnings("ignore")

try:
    import zoneinfo
    IST = zoneinfo.ZoneInfo("Asia/Kolkata")
except ImportError:
    from datetime import timezone
    IST = timezone(timedelta(hours=5, minutes=30))

# ── Schedule constants ────────────────────────────────────────────────────────
MARKET_OPEN  = dtime(9,  30)  # 9:30 AM IST
MARKET_CLOSE = dtime(15, 30)  # 3:30 PM IST

# ── Schedule helpers ──────────────────────────────────────────────────────────

def now_ist() -> datetime:
    return datetime.now(IST)

def is_in_window() -> bool:
    t = now_ist().time()
    return MARKET_OPEN <= t < MARKET_CLOSE

def is_past_close() -> bool:
    return not is_in_window()

def close_timestamp() -> float:
    return now_ist().replace(
        hour=15, minute=30, second=0, microsecond=0
    ).timestamp()

def seconds_until_next_window() -> float:
    now     = now_ist()
    weekday = now.weekday()

    if is_in_window() and weekday < 6:
        return 0

    candidate = now.replace(hour=9, minute=30, second=0, microsecond=0)

    if now.time() >= MARKET_CLOSE or now.time() >= MARKET_OPEN:
        candidate += timedelta(days=1)

    while candidate.weekday() >= 6:
        candidate += timedelta(days=1)

    return max((candidate - now).total_seconds(), 0)

def wait_for_window():
    secs = seconds_until_next_window()
    if secs == 0:
        return
    wake_at = datetime.fromtimestamp(time.time() + secs)
    print(f"\n  🕐  Outside market hours (Mon–Sat 09:30–15:30 IST).")
    print(f"  💤  Sleeping {format_duration(int(secs))} → wake at "
          f"{wake_at.strftime('%A %d %b, %H:%M')}\n")
    time.sleep(secs)

# ── Utility ───────────────────────────────────────────────────────────────────

def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if m else f"{h}h"

def save_screenshot(page, output_dir: str, full_page: bool) -> str:
    """Save a screenshot of just the NSE option chain table."""
    now         = now_ist()
    date_folder = now.strftime("%d-%m-%y")
    time_str    = now.strftime("%H-%M")
    day_dir     = os.path.join(output_dir, date_folder)
    os.makedirs(day_dir, exist_ok=True)
    filepath    = os.path.join(day_dir, f"{time_str}.png")

    # Try to capture just the option chain table
    try:
        page.wait_for_selector(".opttbldata", timeout=20000)
        page.wait_for_timeout(2000)
        table = page.query_selector(".opttbldata")
        if table:
            table.scroll_into_view_if_needed()
            page.wait_for_timeout(1000)
            table.screenshot(path=filepath)
            return filepath
    except Exception:
        pass

    # Fallback — viewport screenshot only (1920x1080)
    page.screenshot(path=filepath, full_page=False)
    return filepath

def close_browser_quietly(browser):
    try:
        browser.close()
    except Exception:
        pass

# ── Main runner ───────────────────────────────────────────────────────────────

def run(args):
    from playwright.sync_api import sync_playwright, Error as PlaywrightError

    url        = args.url
    output_dir = os.path.abspath(args.output)
    interval   = args.interval
    max_count  = args.count
    full_page  = args.fullpage
    manual     = args.manual

    print()
    print("  📸  NSE Option Chain Screenshot Tool")
    print("  " + "─" * 52)
    print(f"  URL      : {url}")
    print(f"  Folder   : {output_dir}")
    print(f"  Interval : every {format_duration(interval)}")
    print(f"  Count    : {'unlimited  (Ctrl+C to stop)' if max_count == 0 else max_count}")
    print(f"  Size     : {args.width}×{args.height}px")
    if manual:
        print(f"  Mode     : MANUAL  ▸  running immediately")
    else:
        print(f"  Mode     : AUTO    ▸  Mon–Sat  09:30–15:30 IST")
    print("  " + "─" * 52)
    print()

    if not manual:
        wait_for_window()

    taken   = 0
    errors  = 0
    browser = None

    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-http2",
                ]
            )
            context = browser.new_context(
                viewport={"width": args.width, "height": args.height},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,image/webp,*/*;q=0.8"
                    ),
                }
            )
            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            print("  🌐  Opening browser and loading page…")
            try:
                page.goto(url, wait_until="load", timeout=60_000)
                page.wait_for_timeout(1500)
                print(f"  ✅  Page loaded: {page.title() or url}\n")
            except Exception as exc:
                print(f"  ❌  Failed to load page: {exc}")
                close_browser_quietly(browser)
                return

            while max_count == 0 or taken < max_count:

                if not manual and is_past_close():
                    print("  🔔  Market closed (15:30 IST). Stopping for today.")
                    break

                now_str = datetime.now().strftime("%H:%M:%S")
                label   = (
                    f"#{taken + 1}"
                    if max_count == 0
                    else f"#{taken + 1}/{max_count}"
                )

                if taken > 0:
                    print(f"  [{now_str}] 🔄  Refreshing page…", end=" ", flush=True)
                    try:
                        page.reload(wait_until="load", timeout=60_000)
                        page.wait_for_timeout(1500)
                        print("done")
                    except (PlaywrightError, Exception) as exc:
                        errors += 1
                        print(f"❌  Reload failed: {exc}")
                else:
                    print(f"  [{now_str}] 📷  First capture {label}…", end=" ", flush=True)

                try:
                    if taken > 0:
                        now_str = datetime.now().strftime("%H:%M:%S")
                        print(f"  [{now_str}] 📷  Capturing {label}…", end=" ", flush=True)

                    filepath = save_screenshot(page, output_dir, full_page)
                    taken   += 1
                    print(f"✅  {os.path.basename(filepath)}")
                except (PlaywrightError, Exception) as exc:
                    errors += 1
                    print(f"❌  Screenshot failed: {exc}")

                if max_count == 0 or taken < max_count:
                    if not manual:
                        sleep_secs = min(
                            interval,
                            max(close_timestamp() - time.time(), 0)
                        )
                        if sleep_secs <= 0:
                            print("  🔔  Market closed (15:30 IST). Stopping for today.")
                            break
                    else:
                        sleep_secs = interval

                    next_at = datetime.fromtimestamp(
                        time.time() + sleep_secs
                    ).strftime("%H:%M:%S")
                    print(
                        f"  ⏳  Next refresh + screenshot in "
                        f"{format_duration(int(sleep_secs))} (at {next_at})\n"
                    )
                    time.sleep(sleep_secs)

    except KeyboardInterrupt:
        print("\n  ⏹️   Stopped by user.")
    except Exception as exc:
        if "TargetClosedError" not in str(exc) and "Target page" not in str(exc):
            print(f"\n  ❌  Unexpected error: {exc}")
    finally:
        close_browser_quietly(browser)

    print()
    print("  " + "─" * 52)
    print(f"  ✅  Done!  {taken} screenshot(s) saved to:")
    print(f"      {output_dir}")
    if errors:
        print(f"  ⚠️   {errors} error(s) occurred (see above)")
    print()

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--output", "-o", default="screenshots")
    parser.add_argument("--interval", "-i", type=int, default=300)
    parser.add_argument("--count", "-n", type=int, default=0)
    parser.add_argument("--fullpage", action="store_true")
    parser.add_argument("--width",  type=int, default=1920)
    parser.add_argument("--height", type=int, default=2500)
    parser.add_argument("--manual", action="store_true")

    args = parser.parse_args()

    if not args.url.startswith(("http://", "https://")):
        args.url = "https://" + args.url

    run(args)

if __name__ == "__main__":
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("\n❌  Run: pip install playwright tzdata && playwright install firefox\n")
        sys.exit(1)

    main()
