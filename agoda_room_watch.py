"""
Agoda room-availability watcher.

Watches a specific Agoda hotel/room for target 1-night stays becoming available
and pushes a Discord notification when one frees up.

Context: booked "270 Starry Sky Pool River Duplex Suite" (Chongqing) for
Sept 9-10, 2026 because that was the only date open. This checks whether the
adjacent nights Sept 8-9 or Sept 10-11 free up so the booking can be moved.

Design notes:
  * Uses a real Chromium via Playwright (Agoda renders availability client-side
    and blocks plain HTTP scrapers).
  * "blocked / captcha" is treated as INCONCLUSIVE -- we never report a date as
    unavailable when we were actually blocked, so you won't get false negatives.
  * Every run saves a screenshot + the room text to ./artifacts so the detection
    heuristic can be tuned against a real run if Agoda changes its markup.

Env vars:
  DISCORD_WEBHOOK_URL   (required for alerts) Discord channel webhook URL
  SEND_ALERTS           "true"/"false", default "true"
  DEBUG_ALWAYS_NOTIFY   "true" -> send a status message to Discord every run
                        (handy for a first manual test of the webhook)
  MAX_JITTER_SECONDS    random sleep before hitting Agoda (default 0; set by CI)
"""

import os
import re
import sys
import time
import random
import json
from dataclasses import dataclass, field
from typing import List, Optional

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# ---------------------------------------------------------------------------
# Config -- everything about the specific hotel/room we are watching.
# ---------------------------------------------------------------------------
HOTEL_ID = "67861443"
CID = "1932646"
CURRENCY = "USD"
ADULTS = 2
ROOMS = 1

# Substring used to identify the room we care about within the room list.
# Kept loose (no degree symbol / punctuation) so minor formatting differences
# on the page still match.
ROOM_NAME_NEEDLE = "Starry Sky Pool River Duplex Suite"

# Target 1-night stays to watch. (check-in date, human label)
TARGET_STAYS = [
    ("2026-09-08", "Sept 8 -> 9"),
    ("2026-09-10", "Sept 10 -> 11"),
]
LOS = 1  # length of stay in nights

ARTIFACT_DIR = "artifacts"

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------
@dataclass
class DateResult:
    checkin: str
    label: str
    status: str = "unknown"          # available | unavailable | blocked | error
    price: Optional[str] = None
    detail: str = ""
    url: str = ""


# Real property-page URL, with {checkin} where the check-in date goes. Taken from
# the browser address bar while viewing the hotel page; session-specific params
# (searchrequestid, ds) were dropped as they aren't needed and go stale. Note the
# query param is lowercase `checkin`. Override at runtime with PROPERTY_URL_TEMPLATE.
# (The bare /hotel/{id}.html deep link does NOT work -- it redirects to the homepage.)
DEFAULT_PROPERTY_URL_TEMPLATE = (
    "https://www.agoda.com/chongqing-indition-high-altitude-hotel/hotel/chongqing-cn.html"
    "?countryId=191&finalPriceView=1&isShowMobileAppPrice=false"
    f"&cid={CID}&familyMode=false&adults={ADULTS}&children=0&rooms={ROOMS}&maxRooms=0"
    f"&currencyCode={CURRENCY}&los={LOS}&checkin={{checkin}}"
)
PROPERTY_URL_TEMPLATE = (
    os.getenv("PROPERTY_URL_TEMPLATE", "").strip() or DEFAULT_PROPERTY_URL_TEMPLATE
)


def build_url(checkin: str) -> str:
    if PROPERTY_URL_TEMPLATE:
        if "{checkin}" in PROPERTY_URL_TEMPLATE:
            return PROPERTY_URL_TEMPLATE.format(checkin=checkin)
        # template has a literal date query param -- swap it out
        return re.sub(r"(checkIn=)\d{4}-\d{2}-\d{2}", rf"\g<1>{checkin}",
                      PROPERTY_URL_TEMPLATE, flags=re.IGNORECASE)
    # Fallback (known to redirect to homepage -- replace via template above).
    return (
        f"https://www.agoda.com/hotel/{HOTEL_ID}.html"
        f"?checkIn={checkin}"
        f"&los={LOS}"
        f"&adults={ADULTS}"
        f"&rooms={ROOMS}"
        f"&cid={CID}"
        f"&currencyCode={CURRENCY}"
    )


# JavaScript run inside the page to extract availability for our target room.
# Returns a plain JSON-serializable object; Python interprets it.
#
# Detection is per-room only (no unreliable "whole property sold out" heuristic).
# It also returns `roomNames` -- every room name it can see on the page -- which
# is logged so the matching can be tuned against reality if Agoda changes markup.
PAGE_PROBE_JS = r"""
(needle) => {
  const norm = s => (s || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  const needleN = norm(needle);
  const bodyText = (document.body && document.body.innerText) || "";

  // --- bot / block detection (specific patterns only) ---
  const blocked = /captcha|verify (you are|you're) human|unusual traffic|access denied|press *& *hold|are you a robot|perimeterx|request blocked/i.test(bodyText)
    || !!document.querySelector('#px-captcha, iframe[src*="captcha"]');

  // --- collect candidate room-name strings from the room grid ---
  const nameSelectors = [
    '[data-selenium="masterroom-title"]',
    '[data-selenium="room-title"]',
    '[data-selenium="rt-name"]',
    '[data-element-name="room-name"]',
    '[id^="roomGrid"] h3',
    '[data-selenium="MasterRoom"] h3',
    '[data-testid*="room"] h3',
    'h3', 'h2',
  ];
  const nameSet = new Set();
  const nameEls = [];
  for (const sel of nameSelectors) {
    document.querySelectorAll(sel).forEach(el => {
      const t = (el.innerText || "").trim();
      if (t && t.length <= 120) { nameSet.add(t); nameEls.push(el); }
    });
  }
  const roomNames = Array.from(nameSet);

  // --- locate the target room's name element, then climb to its card ---
  let matchEl = nameEls.find(el => norm(el.innerText).includes(needleN)) || null;
  if (!matchEl) {
    // broad fallback: smallest element containing the room name text
    const hits = Array.from(document.querySelectorAll('div,section,article,li,span,td'))
      .filter(el => norm(el.innerText).includes(needleN))
      .sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length);
    matchEl = hits[0] || null;
  }
  const roomFound = !!matchEl;

  const priceRe = /(US\$|USD|\$|¥|CNY)\s?[\d,]{2,}/;
  const soldLocalRe = /sold ?out|no longer available|not available|unavailable|no rooms? (left|available)/i;
  const bookRe = /reserve|book now|select room/i;

  // Climb up from the room name until we reach the container that holds the whole
  // master-room block -- i.e. one that contains BOTH the name and the price (or a
  // Reserve/Book button). The name sits in the photo/details panel; price lives in
  // a sibling offer row, so a too-early stop misses it. Fall back to the topmost
  // ancestor we visited if none qualifies.
  let card = matchEl;
  let cardText = matchEl ? (matchEl.innerText || "") : "";
  for (let i = 0; i < 12 && card && card.parentElement; i++) {
    const t = card.innerText || "";
    if (norm(t).includes(needleN) && (priceRe.test(t) || bookRe.test(t))) {
      cardText = t;
      break;
    }
    cardText = t;
    card = card.parentElement;
  }

  const priceMatch = cardText.match(priceRe);
  const price = priceMatch ? priceMatch[0] : null;
  const hasBookBtn = bookRe.test(cardText)
    || !!(card && card.querySelector('[data-selenium="booking-button"],[data-element-name*="book"],[data-selenium*="reserve"]'));
  const soldOut = soldLocalRe.test(cardText);
  const bookable = roomFound && !soldOut && (!!price || hasBookBtn);

  // Did we actually land on the property page (vs. a homepage/search redirect)?
  const hasPropertyMarkers = !!document.querySelector(
    '[data-selenium="hotel-header-name"],[data-selenium="MasterRoom"],[id^="roomGrid"],[data-element-name="room-grid"]'
  );
  const onPropertyUrl = /\/hotel\//i.test(location.href) || location.href.includes("hotelId=");

  return {
    blocked,
    roomFound,
    bookable,
    price,
    soldOut,
    hasBookBtn,
    roomNames,
    roomCount: roomNames.length,
    cardExcerpt: cardText.slice(0, 600),
    bodyLen: bodyText.length,
    finalUrl: location.href,
    title: document.title,
    hasPropertyMarkers,
    onPropertyUrl,
  };
}
"""


def check_date(page, checkin: str, label: str) -> DateResult:
    url = build_url(checkin)
    res = DateResult(checkin=checkin, label=label, url=url)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except PWTimeoutError:
        res.status = "error"
        res.detail = "navigation timeout"
        return res

    # Let the SPA render, then scroll through the page to trigger lazy-loading of
    # the room cards (Agoda only mounts room rows as they scroll into view).
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except PWTimeoutError:
        pass
    _scroll_to_load_rooms(page)
    # Wait for the specific room name to render (best case), else settle briefly.
    try:
        page.wait_for_selector(f"text={ROOM_NAME_NEEDLE}", timeout=10_000)
    except PWTimeoutError:
        page.wait_for_timeout(random.randint(2000, 4000))

    _save_artifacts(page, checkin)

    try:
        probe = page.evaluate(PAGE_PROBE_JS, ROOM_NAME_NEEDLE)
    except Exception as e:  # noqa: BLE001
        res.status = "error"
        res.detail = f"probe failed: {e}"
        return res

    res.price = probe.get("price")
    landed_on_property = probe.get("hasPropertyMarkers") or probe.get("onPropertyUrl")
    room_count = probe.get("roomCount", 0)

    if probe.get("blocked"):
        res.status = "blocked"
        res.detail = "bot-check / captcha detected (inconclusive)"
    elif not landed_on_property:
        # Redirect to homepage/search or a bot-wall shell -> INCONCLUSIVE.
        res.status = "blocked"
        res.detail = (f"did not land on property page -- {probe.get('finalUrl')} "
                      f"(title={probe.get('title')!r}, len={probe.get('bodyLen')})")
    elif probe.get("bookable"):
        res.status = "available"
        res.detail = "room found and bookable"
    elif probe.get("roomFound"):
        res.status = "unavailable"
        res.detail = "target room listed but not bookable (sold out)"
    elif room_count == 0:
        # On the property page but no room names parsed -> grid didn't load.
        # Inconclusive, not a real "unavailable".
        res.status = "blocked"
        res.detail = "no rooms parsed on property page (grid did not load)"
    else:
        res.status = "unavailable"
        res.detail = f"target room not offered ({room_count} other rooms seen)"

    print(f"    probe: {json.dumps({k: probe.get(k) for k in ('blocked','roomFound','bookable','price','soldOut','hasBookBtn','roomCount','bodyLen','hasPropertyMarkers','onPropertyUrl')})}")
    print(f"    roomNames: {probe.get('roomNames', [])}")
    if probe.get("cardExcerpt"):
        print(f"    cardExcerpt: {probe.get('cardExcerpt','')[:300].replace(chr(10),' | ')}")
    return res


def _scroll_to_load_rooms(page) -> None:
    """Scroll down the page in steps so lazy-mounted room cards render."""
    try:
        for _ in range(12):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(random.randint(500, 900))
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
    except Exception as e:  # noqa: BLE001
        print(f"    (scroll failed: {e})")


def _save_artifacts(page, checkin: str) -> None:
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    stub = os.path.join(ARTIFACT_DIR, f"agoda_{checkin}")
    try:
        page.screenshot(path=f"{stub}.png", full_page=True)
    except Exception as e:  # noqa: BLE001
        print(f"    (screenshot failed: {e})")
    try:
        with open(f"{stub}.html", "w", encoding="utf-8") as fh:
            fh.write(page.content())
    except Exception as e:  # noqa: BLE001
        print(f"    (html dump failed: {e})")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def send_discord(webhook_url: str, content: str) -> None:
    if not webhook_url:
        print("No DISCORD_WEBHOOK_URL set -- skipping Discord notification.")
        return
    try:
        resp = requests.post(webhook_url, json={"content": content}, timeout=30)
        if resp.status_code in (200, 204):
            print("Discord notification sent.")
        else:
            print(f"Discord returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:  # noqa: BLE001
        print(f"Failed to send Discord notification: {e}")


USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def main() -> int:
    # Optional: check a single arbitrary date (e.g. a known-available one) to
    # validate that detection reports AVAILABLE. Set TEST_CHECKIN=YYYY-MM-DD.
    test_checkin = os.getenv("TEST_CHECKIN", "").strip()

    # --- jitter so we don't hit Agoda at a predictable clock time (skip in test) ---
    max_jitter = int(os.getenv("MAX_JITTER_SECONDS", "0") or "0")
    if max_jitter > 0 and not test_checkin:
        wait = random.randint(0, max_jitter)
        print(f"Jitter: sleeping {wait}s before checking...")
        time.sleep(wait)

    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    send_alerts = os.getenv("SEND_ALERTS", "true").lower() != "false"
    debug_notify = os.getenv("DEBUG_ALWAYS_NOTIFY", "false").lower() == "true"

    stays = [(test_checkin, f"TEST {test_checkin}")] if test_checkin else TARGET_STAYS

    user_agent = random.choice(USER_AGENTS)
    results: List[DateResult] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=user_agent,
            locale="en-US",
            timezone_id="America/Los_Angeles",
            viewport={"width": 1366, "height": 900},
        )
        # light stealth: hide the webdriver flag
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = context.new_page()

        for checkin, label in stays:
            print(f"Checking {label} (checkIn={checkin}) ...")
            res = check_date(page, checkin, label)
            print(f"  -> {res.status.upper()}: {res.detail}"
                  + (f" (price {res.price})" if res.price else ""))
            results.append(res)
            # human-ish pause between the two date checks
            page.wait_for_timeout(random.randint(3000, 7000))

        browser.close()

    # --- decide on notifications ---
    available = [r for r in results if r.status == "available"]

    if available and send_alerts:
        lines = ["@here **Agoda room opened up!** :tada:",
                 f"Room: {ROOM_NAME_NEEDLE}", ""]
        for r in available:
            price = f" - {r.price}" if r.price else ""
            lines.append(f"- **{r.label}** is BOOKABLE{price}\n  {r.url}")
        lines.append("\nGo move your booking (this repeats hourly until you do or you disable the workflow).")
        send_discord(webhook, "\n".join(lines))
    elif debug_notify:
        summary = " | ".join(f"{r.label}: {r.status}" for r in results)
        send_discord(webhook, f"[agoda-watch debug] {summary}")

    # --- console summary ---
    print("\n=== Summary ===")
    for r in results:
        print(f"{r.label:14} {r.status.upper():12} {r.detail}")

    # If every date was blocked, surface a non-zero-ish note (but don't fail the
    # job -- a transient block shouldn't page anyone).
    if results and all(r.status in ("blocked", "error") for r in results):
        print("\nWARNING: all checks were blocked/errored -- results are inconclusive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
