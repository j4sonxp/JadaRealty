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
PAGE_PROBE_JS = r"""
(needle) => {
  const bodyText = (document.body && document.body.innerText) || "";

  // --- bot / block detection ---
  const blockPatterns = [
    /captcha/i, /verify (you are|you're) human/i, /unusual traffic/i,
    /access denied/i, /press *& *hold/i, /are you a robot/i,
    /px-captcha/i, /perimeterx/i, /request blocked/i
  ];
  const blocked = blockPatterns.some(re => re.test(bodyText))
    || !!document.querySelector('#px-captcha, iframe[src*="captcha"]');

  // --- whole-property sold out ---
  const soldOutGlobalRe =
    /fully booked|no rooms? (available|left)|sold ?out for (these|your) dates|not available for (your|these) dates|no availability/i;
  const soldOutGlobal = soldOutGlobalRe.test(bodyText);

  // --- try to locate the target room card(s) ---
  const norm = s => (s || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  const needleN = norm(needle);

  // Candidate room containers Agoda has used historically; fall back to a broad
  // sweep of elements whose own text mentions the room name.
  let candidates = Array.from(document.querySelectorAll(
    '[data-selenium="MasterRoom"],[data-testid*="MasterRoom"],[data-selenium="masterRoom"],[id^="roomGrid"] [class*="Master"],[data-element-name="master-room"]'
  ));

  const textHasNeedle = el => norm(el.innerText).includes(needleN);

  if (!candidates.length) {
    // broad fallback: smallest elements that contain the room name text
    const all = Array.from(document.querySelectorAll('div,section,article,li'));
    candidates = all.filter(el => textHasNeedle(el))
      // prefer the most specific (fewest descendants) matches
      .sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)
      .slice(0, 5);
  } else {
    candidates = candidates.filter(textHasNeedle);
  }

  const priceRe = /(US\$|USD|\$|¥|CNY)\s?[\d,]+/;
  const soldOutLocalRe = /sold ?out|no longer available|not available|unavailable/i;
  const bookRe = /book now|reserve|select|choose/i;

  let roomFound = candidates.length > 0;
  let bookable = false;
  let price = null;
  let excerpt = "";

  for (const el of candidates) {
    const t = el.innerText || "";
    excerpt = t.slice(0, 1200);
    const hasPrice = priceRe.test(t);
    const hasBook = bookRe.test(t);
    const soldLocal = soldOutLocalRe.test(t);
    if (hasPrice) {
      const m = t.match(priceRe);
      if (m) price = m[0];
    }
    if ((hasPrice || hasBook) && !soldLocal) {
      bookable = true;
      break;
    }
  }

  // If we never found the room card, capture a small slice of body for debugging.
  if (!excerpt) excerpt = bodyText.slice(0, 1200);

  // Did we actually land on the property page (vs. a homepage/search redirect)?
  const propertyMarkers = [
    '[data-selenium="hotel-header-name"]',
    '[data-selenium="masterroom"]',
    '[data-selenium="MasterRoom"]',
    '[id^="roomGrid"]',
    '[data-element-name="room-grid"]',
    '[data-selenium="area-city"]',
  ];
  const hasPropertyMarkers = propertyMarkers.some(sel => document.querySelector(sel));
  const onPropertyUrl = /\/hotel\//i.test(location.href) || location.href.includes("hotelId=");

  return {
    blocked,
    soldOutGlobal,
    roomFound,
    bookable,
    price,
    excerpt,
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

    # Give the SPA time to render the room grid. Wait for the room name or a
    # sold-out signal, whichever comes first; fall back to a fixed settle time.
    try:
        page.wait_for_selector("text=/room|sold|unavailable|captcha/i", timeout=25_000)
    except PWTimeoutError:
        pass
    # a little extra settle + human-ish pause
    page.wait_for_timeout(random.randint(2500, 5000))

    _save_artifacts(page, checkin)

    try:
        probe = page.evaluate(PAGE_PROBE_JS, ROOM_NAME_NEEDLE)
    except Exception as e:  # noqa: BLE001
        res.status = "error"
        res.detail = f"probe failed: {e}"
        return res

    res.price = probe.get("price")
    landed_on_property = probe.get("hasPropertyMarkers") or probe.get("onPropertyUrl")

    if probe.get("blocked"):
        res.status = "blocked"
        res.detail = "bot-check / captcha detected (inconclusive)"
    elif probe.get("bookable"):
        res.status = "available"
        res.detail = "room found and bookable"
    elif not landed_on_property:
        # We never reached the property page (redirect to homepage/search, or a
        # bot-wall shell). Treat as INCONCLUSIVE, never as "unavailable".
        res.status = "blocked"
        res.detail = (f"did not land on property page -- redirected to "
                      f"{probe.get('finalUrl')} (title={probe.get('title')!r}, "
                      f"len={probe.get('bodyLen')})")
    elif probe.get("soldOutGlobal"):
        res.status = "unavailable"
        res.detail = "property sold out for these dates"
    elif probe.get("roomFound"):
        res.status = "unavailable"
        res.detail = "room listed but not bookable (sold out)"
    else:
        res.status = "unavailable"
        res.detail = "target room not offered for these dates"

    print(f"    probe: {json.dumps({k: probe.get(k) for k in ('blocked','soldOutGlobal','roomFound','bookable','price','bodyLen','hasPropertyMarkers','onPropertyUrl','finalUrl')})}")
    print(f"    excerpt: {probe.get('excerpt','')[:300].replace(chr(10),' | ')}")
    return res


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
