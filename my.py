#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════╗
║          Website Screenshot Tool  📸                 ║
║  Keeps a browser open, refreshes the page every      ║
║  N minutes, and saves a timestamped screenshot.      ║
║                                                      ║
║  Auto mode : runs only Mon–Fri, 9:30 AM – 3:30 PM   ║
║  Manual    : add --manual to run anytime instantly   ║
╚══════════════════════════════════════════════════════╝

SETUP (run once):
    pip install playwright
    playwright install firefox

USAGE:
    # Auto mode – waits for trading hours, runs Mon–Fri 9:30–15:30
    python website_screenshotter.py https://www.nseindia.com/option-chain

    # Manual mode – runs immediately, no schedule check
    python website_screenshotter.py https://www.nseindia.com/option-chain --manual

    # Custom interval (e.g. every 60 seconds)
    python website_screenshotter.py https://... --interval 60

    # Take exactly 10 screenshots then stop
    python website_screenshotter.py https://... --count 10

    # Capture full scrollable page
    python website_screenshotter.py https://... --fullpage

Press Ctrl+C at any time to stop.
"""

import os
import sys
import time
import argparse
from datetime import datetime, time as dtime, timedelta

try:
    import zoneinfo
    IST = zoneinfo.ZoneInfo("Asia/Kolkata")
except ImportError:
    # Python < 3.9 fallback
    from datetime import timezone
    IST = timezone(timedelta(hours=5, minutes=30))


# ── Schedule constants ────────────────────────────────────────────────────────
MARKET_OPEN  = dtime(9, 30)   # 9:30 AM IST
MARKET_CLOSE = dtime(15, 30)  # 3:30 PM IST


# ── Schedule helpers ──────────────────────────────────────────────────────────

def now_ist() -> datetime:
    """Current datetime in IST."""
    return datetime.now(IST)


def seconds_until_next_window() -> float:
    """
    Returns seconds to sleep before the next Mon–Fri 9:30–15:30 IST window.
    Returns 0 if already inside the window.
    """
    now      = now_ist()
    weekday  = now.weekday()        # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    cur_time = now.time()

    # Already inside the window?
    if weekday < 5 and MARKET_OPEN <= cur_time < MARKET_CLOSE:
        return 0

    # Build next valid open datetime at 9:30 AM IST
    candidate = now.replace(hour=9, minute=30, second=0, microsecond=0)

    if weekday < 5 and cur_time >= MARKET_CLOSE:
        # Past close today → try tomorrow
        candidate += timedelta(days=1)
    elif weekday >= 5:
        # Weekend → jump to Monday
        candidate += timedelta(days=(7 - weekday))

    # Safety: skip any remaining weekend days
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)

    return max((candidate - now).total_seconds(), 0)


def is_past_close() -> bool:
    """True if current IST time is at or after 3:30 PM."""
    return now_ist().time() >= MARKET_CLOSE


def wait_for_window():
    """Block until the next valid IST window opens, with a status message."""
    secs = seconds_until_next_window()
    if secs == 0:
        return  # already inside the window

    wake_at = datetime.fromtimestamp(time.time() + secs)
    print(f"\n  🕐  Outside trading hours (Mon–Fri 09:30–15:30 IST).")
    print(f"  💤  Sleeping {format_duration(int(secs))} → wake at "
          f"{wake_at.strftime('%A %d %b, %H:%M')}\n")
    time.sleep(secs)


# ── Utility ───────────────────────────────────────────────────────────────────

def format_duration(seconds: int) -> str:
    """Return a human-readable duration string."""
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if m else f"{h}h"

def upload_to_github(filepath: str):
    """Upload screenshot to GitHub repo."""
    import base64, requests, os

    token  = os.environ.get("GITHUB_TOKEN")
    repo   = os.environ.get("GITHUB_REPO")
    branch = os.environ.get("GITHUB_BRANCH", "main")

    if not token or not repo:
        return

    with open(filepath, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    # Path inside repo e.g. screenshots/04-06-26/09-30.png
    rel_path = filepath.split("screenshots/")[-1]
    api_url  = f"https://api.github.com/repos/{repo}/contents/screenshots/{rel_path}"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Check if file exists (need SHA to update)
    sha = None
    r = requests.get(api_url, headers=headers)
    if r.status_code == 200:
        sha = r.json().get("sha")

    data = {
        "message": f"📸 {rel_path}",
        "content": content,
        "branch": branch
    }
    if sha:
        data["sha"] = sha

    requests.put(api_url, json=data, headers=headers)


def save_screenshot(page, output_dir: str, full_page: bool) -> str:
    """Save a screenshot of the NSE option chain table or full page."""
    # Create a subfolder named after today's date e.g. 04-06-25
    date_folder = now_ist().strftime("%d-%m-%y")
    time_str    = now_ist().strftime("%H-%M")
    day_dir     = os.path.join(output_dir, date_folder)
    os.makedirs(day_dir, exist_ok=True)
    filepath    = os.path.join(day_dir, f"{time_str}.png")

    # Try to capture just the option chain table
    try:
        page.wait_for_selector(".opttbldata", timeout=15000)
        table = page.query_selector(".opttbldata")
        if table:
            table.scroll_into_view_if_needed()
            page.wait_for_timeout(1000)
            table.screenshot(path=filepath)
            upload_to_github(filepath)
            return filepath
    except Exception:
        pass

    # Fallback — full page screenshot
    page.screenshot(path=filepath, full_page=True)
    return filepath


# ── Main runner ───────────────────────────────────────────────────────────────

def run(args):
    from playwright.sync_api import sync_playwright

    url        = args.url
    output_dir = os.path.abspath(args.output)
    interval   = args.interval
    max_count  = args.count
    full_page  = args.fullpage
    manual     = args.manual

    # ── Header ───────────────────────────────────────────────────────────────
    print()
    print("  📸  Website Screenshot Tool")
    print("  " + "─" * 52)
    print(f"  URL      : {url}")
    print(f"  Folder   : {output_dir}")
    print(f"  Interval : every {format_duration(interval)}")
    print(f"  Count    : {'unlimited  (Ctrl+C to stop)' if max_count == 0 else max_count}")
    print(f"  Full-page: {'yes' if full_page else 'no'}")
    print(f"  Size     : {args.width}×{args.height}px")
    if manual:
        print(f"  Mode     : MANUAL  ▸  running immediately, no schedule check")
    else:
        print(f"  Mode     : AUTO    ▸  Mon–Fri  09:30–15:30 IST")
    print("  " + "─" * 52)
    print()

    # ── Schedule gate (skipped in manual mode) ────────────────────────────────
    if not manual:
        wait_for_window()

    taken  = 0
    errors = 0

    with sync_playwright() as p:
        # Launch browser once; keep it alive for the whole session
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
            browser.close()
            return

        try:
            while max_count == 0 or taken < max_count:

                # ── In auto mode, stop at market close ────────────────────
                if not manual and is_past_close():
                    print("  🔔  Market closed (15:30 IST). Stopping for today.")
                    break

                now_str = datetime.now().strftime("%H:%M:%S")
                label   = (
                    f"#{taken + 1}"
                    if max_count == 0
                    else f"#{taken + 1}/{max_count}"
                )

                # ── Refresh (skip on the very first capture) ──────────────
                if taken > 0:
                    print(f"  [{now_str}] 🔄  Refreshing page…", end=" ", flush=True)
                    try:
                        page.reload(wait_until="load", timeout=60_000)
                        page.wait_for_timeout(1500)
                        print("done")
                    except Exception as exc:
                        errors += 1
                        print(f"❌  Reload failed: {exc}")
                else:
                    print(f"  [{now_str}] 📷  First capture {label}…", end=" ", flush=True)

                # ── Screenshot ────────────────────────────────────────────
                try:
                    if taken > 0:
                        now_str = datetime.now().strftime("%H:%M:%S")
                        print(f"  [{now_str}] 📷  Capturing {label}…", end=" ", flush=True)

                    filepath = save_screenshot(page, output_dir, full_page)
                    taken   += 1
                    print(f"✅  {os.path.basename(filepath)}")
                except Exception as exc:
                    errors += 1
                    print(f"❌  Screenshot failed: {exc}")

                # ── Wait for next cycle ───────────────────────────────────
                if max_count == 0 or taken < max_count:
                    if not manual:
                        # Cap sleep so we don't overshoot market close
                        close_ts   = now_ist().replace(
                            hour=15, minute=30, second=0, microsecond=0
                        ).timestamp()
                        sleep_secs = min(interval, max(close_ts - time.time(), 0))

                        if sleep_secs <= 0:
                            print("  🔔  Market closed (15:30 IST). Stopping for today.")
                            break
                    else:
                        sleep_secs = interval

                    next_at = datetime.fromtimestamp(time.time() + sleep_secs).strftime("%H:%M:%S")
                    print(
                        f"  ⏳  Next refresh + screenshot in "
                        f"{format_duration(int(sleep_secs))} (at {next_at})\n"
                    )
                    time.sleep(sleep_secs)

        except KeyboardInterrupt:
            print("\n  ⏹️   Stopped by user.")

        finally:
            browser.close()

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print("  " + "─" * 52)
    print(f"  ✅  Done!  {taken} screenshot(s) saved to:")
    print(f"      {output_dir}")
    if errors:
        print(f"  ⚠️   {errors} error(s) occurred (see above)")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=(
            "📸 Refresh a website every N seconds and screenshot it.\n"
            "Auto mode runs only Mon–Fri 09:30–15:30 IST.\n"
            "Use --manual to run immediately regardless of time."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "url",
        help="Website URL to monitor (https:// added automatically if missing)"
    )
    parser.add_argument(
        "--output", "-o", default="screenshots",
        help="Output folder (default: screenshots/)"
    )
    parser.add_argument(
        "--interval", "-i", type=int, default=300,
        help="Seconds between refresh + screenshot (default: 300 = 5 min)"
    )
    parser.add_argument(
        "--count", "-n", type=int, default=0,
        help="Max screenshots; 0 = run until close (default: 0)"
    )
    parser.add_argument(
        "--fullpage", action="store_true",
        help="Capture entire scrollable page, not just the viewport"
    )
    parser.add_argument(
        "--width",  type=int, default=1920,
        help="Viewport width in px (default: 1920)"
    )
    parser.add_argument(
        "--height", type=int, default=1080,
        help="Viewport height in px (default: 1080)"
    )
    parser.add_argument(
        "--manual", action="store_true",
        help="Run immediately without any schedule check (use for manual runs)"
    )

    args = parser.parse_args()

    # Auto-prepend https:// if missing
    if not args.url.startswith(("http://", "https://")):
        args.url = "https://" + args.url
        print(f"ℹ️  Auto-added https:// → {args.url}")

    run(args)


if __name__ == "__main__":
    try:
        import playwright  # noqa: F401
    except ImportError:
        print(
            "\n❌  Playwright not installed.\n"
            "   Run these two commands first:\n\n"
            "       pip install playwright\n"
            "       playwright install firefox\n"
        )
        sys.exit(1)

    main()
