import requests
import icalendar
import ssl
import os
import json
import base64
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from datetime import datetime, date, timedelta
from dataclasses import dataclass
from typing import List, Dict
from urllib3.exceptions import InsecureRequestWarning
import urllib3

urllib3.disable_warnings(InsecureRequestWarning)
SEND_EMAIL = True
SEND_DISCORD = True

# When true, no email/Discord is sent and the state file is written locally but
# NOT committed to GitHub. Set DRY_RUN=true to test cancellation detection
# without pinging the channel or touching the repo. Defaults off in production.
DRY_RUN = os.getenv("DRY_RUN", "false").strip().lower() in ("1", "true", "yes")

# --- Cancellation-detection state (snapshot committed to the repo) ---
STATE_FILE = "reservations_state.json"
GITHUB_USERNAME = "j4sonxp"
GITHUB_REPO = "JadaRealty"
GITHUB_BRANCH = "main"
GITHUB_TOKEN = os.getenv("GH_JADA_TOKEN")
LISTINGS = {
    "airbnb_5_unit": {
        "ics_url": "https://www.airbnb.com/calendar/ical/1351763334542458685.ics?s=deaac409c66150df2ef3c9b875eb8b76",
        "calendar_url": "https://www.airbnb.com/multicalendar/1351763334542458685",
        "shared_units": ['airbnb_6_unit', 'airbnb_7_unit', 'airbnb_9_unit', 'airbnb_middle_unit', 'airbnb_back_unit']
    },
    "airbnb_6_unit": {
        "ics_url": "https://www.airbnb.com/calendar/ical/1332667208029769033.ics?s=30ddb4057b83a59c25d916972d549fb6",
        "calendar_url": "https://www.airbnb.com/multicalendar/1332667208029769033",
        "shared_units": ['airbnb_5_unit', 'airbnb_7_unit', 'airbnb_9_unit', 'airbnb_front_unit', 'airbnb_back_unit']
    },
    "airbnb_7_unit": {
        "ics_url": "https://www.airbnb.com/calendar/ical/1323430565127946474.ics?s=ec35ad80ef8e8d486bfe7e74a10bedfb",
        "calendar_url": "https://www.airbnb.com/multicalendar/1323430565127946474",
        "shared_units": ['airbnb_6_unit', 'airbnb_5_unit', 'airbnb_9_unit', 'airbnb_middle_unit', 'airbnb_front_unit']
    },
    "airbnb_9_unit": {
        "ics_url": "https://www.airbnb.com/calendar/ical/1332645461888533290.ics?s=13ceef6faeef83e75c16b81afea7c566",
        "calendar_url": "https://www.airbnb.com/multicalendar/1332645461888533290",
        "shared_units": ['airbnb_6_unit', 'airbnb_7_unit', 'airbnb_5_unit', 'airbnb_middle_unit', 'airbnb_back_unit', 'airbnb_front_unit']
    },
    "airbnb_middle_unit": {
        "ics_url": "https://www.airbnb.com/calendar/ical/1032841991458879387.ics?s=58aba5da2eff2968aaad58a64b32c802",
        "calendar_url": "https://www.airbnb.com/multicalendar/1032841991458879387",
        "shared_units": ['airbnb_5_unit', 'airbnb_7_unit', 'airbnb_9_unit']
    },
    "airbnb_front_unit": {
        "ics_url": "https://www.airbnb.com/calendar/ical/27507605.ics?s=a8b9bcc45e6790606431bea118b35f6b",
        "calendar_url": "https://www.airbnb.com/multicalendar/27507605",
        "shared_units": ['airbnb_6_unit', 'airbnb_7_unit', 'airbnb_9_unit']
    },
    "airbnb_back_unit": {
        "ics_url": "https://www.airbnb.com/calendar/ical/929199535851759140.ics?s=fb189684659d74538e93c7d89ecbad51",
        "calendar_url": "https://www.airbnb.com/multicalendar/929199535851759140",
        "shared_units": ['airbnb_6_unit', 'airbnb_5_unit', 'airbnb_9_unit']
    },
    "vrbo_5_unit": {
        "ics_url": "http://www.vrbo.com/icalendar/68fd8b02f0d9432db28bfb1dc248f79a.ics?nonTentative",
        "calendar_url": "https://www.vrbo.com/p/calendar/321.4378374.4952543",
        "shared_units": ['airbnb_6_unit', 'airbnb_7_unit', 'airbnb_9_unit', 'airbnb_middle_unit', 'airbnb_back_unit']
    },
    "vrbo_6_unit": {
        "ics_url": "http://www.vrbo.com/icalendar/a4bfa1bbf5724c889cb8d4de66dd6294.ics?nonTentative",
        "calendar_url": "https://www.vrbo.com/p/calendar/321.3839034.4413179",
        "shared_units": ['airbnb_5_unit', 'airbnb_7_unit', 'airbnb_9_unit', 'airbnb_front_unit', 'airbnb_back_unit']
    },
    "vrbo_7_unit": {
        "ics_url": "http://www.vrbo.com/icalendar/ad6a59d251024dd6be3d4c2fda7216d2.ics?nonTentative",
        "calendar_url": "https://www.vrbo.com/p/calendar/321.4378390.4952559",
        "shared_units": ['airbnb_6_unit', 'airbnb_5_unit', 'airbnb_9_unit', 'airbnb_middle_unit', 'airbnb_front_unit']
    },
    "vrbo_9_unit": {
        "ics_url": "http://www.vrbo.com/icalendar/e84cf542724f4578987680d18dde0b2d.ics?nonTentative",
        "calendar_url": "https://www.vrbo.com/p/calendar/321.4378375.4952544",
        "shared_units": ['airbnb_6_unit', 'airbnb_7_unit', 'airbnb_5_unit', 'airbnb_middle_unit', 'airbnb_back_unit', 'airbnb_front_unit']
    },
    "vrbo_middle_unit": {
        "ics_url": "http://www.vrbo.com/icalendar/ba242c71cc0947d290727473ee6030e2.ics?nonTentative",
        "calendar_url": "https://www.vrbo.com/p/calendar/321.3839117.4413262",
        "shared_units": ['airbnb_5_unit', 'airbnb_7_unit', 'airbnb_9_unit']
    },
    "vrbo_front_unit": {
        "ics_url": "http://www.vrbo.com/icalendar/55cd404350c44292853e559e626bcfd4.ics?nonTentative",
        "calendar_url": "https://www.vrbo.com/p/calendar/321.3658614.4232759",
        "shared_units": ['airbnb_6_unit', 'airbnb_7_unit', 'airbnb_9_unit']
    },
    "vrbo_back_unit": {
        "ics_url": "http://www.vrbo.com/icalendar/7e15a6276db44ac4a8a65247aa5d9c0b.ics?nonTentative",
        "calendar_url": "https://www.vrbo.com/p/calendar/321.3509190.4082336",
        "shared_units": ['airbnb_6_unit', 'airbnb_5_unit', 'airbnb_9_unit']
    },
}

@dataclass
class Booking:
    listing: str
    start: date
    end: date
    status: str   # booked, blocked, cancelled, tentative, unknown
    summary: str
    uid: str

def _as_date(v):
    """Normalize DTSTART/DTEND to date."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    raise ValueError(f"Unsupported date type: {type(v)}")


def _infer_status(component) -> str:
    """Map iCal fields into normalized statuses."""
    raw_status = str(component.get("STATUS", "")).upper()
    summary = str(component.get("SUMMARY", "")).lower()

    if raw_status == "CANCELLED" or "cancelled" in summary:
        return "cancelled"
    if raw_status == "TENTATIVE":
        return "tentative"
    if "not available" in summary or "blocked" in summary:
        return "blocked"
    if raw_status == "CONFIRMED" or "reservation" in summary or "reserved" in summary:
        return "booked"
    return "booked" if summary else "unknown"


def fetch_calendar(url: str, listing_name: str) -> List[Booking]:
    """Fetch a single iCal and return Booking objects."""
    resp = requests.get(url, timeout=30, verify=False)
    resp.raise_for_status()
    cal = icalendar.Calendar.from_ical(resp.text)

    today = date.today()
    bookings = []

    for comp in cal.walk("VEVENT"):
        dtstart = comp.get("DTSTART")
        dtend = comp.get("DTEND")
        if not dtstart or not dtend:
            continue

        start = _as_date(dtstart.dt)
        end = _as_date(dtend.dt)

        # 🚫 Skip past reservations that ended before today
        if end < today:
            continue

        bookings.append(
            Booking(
                listing=listing_name,
                start=start,
                end=end,
                status=_infer_status(comp),
                summary=str(comp.get("SUMMARY", "")),
                uid=str(comp.get("UID", "")),
            )
        )

    return bookings



def fetch_all_listings(listings_dict: dict) -> List[Booking]:
    """Fetch all listings from LISTINGS dict."""
    all_bookings: List[Booking] = []
    for listing_name, data in listings_dict.items():
        ics_url = data.get("ics_url")
        if not ics_url:
            print(f"❌ No ics_url for {listing_name}")
            continue
        try:
            bookings = fetch_calendar(ics_url, listing_name)
            all_bookings.extend(bookings)
        except Exception as e:
            print(f"❌ Failed to fetch {listing_name}: {e}")
    return all_bookings


def detect_conflicts(bookings: List[Booking],
                                    main_unit: str,
                                    units: List[str]):
    conflicts = []
    whole_reservations = [b for b in bookings if b.listing == main_unit]

    for res in whole_reservations:
        block_start = res.start
        block_end = res.end - timedelta(days=1)
        if res.status == "booked":
            # Check which units need to be blocked
            for unit in units:
                unit_bookings = [
                    b for b in bookings if b.listing == unit and b.status in ("booked", "blocked")
                ]
                overlap = any(not (res.end <= ub.start or res.start >= ub.end) for ub in unit_bookings)
                if not overlap:
                    conflicts.append({
                        "unit": unit,
                        "start": res.start,
                        "end": res.end,
                        "reason": f"{main_unit} reserved {res.start} → {res.end}, Block off {block_start} → {block_end} for {unit}"
                    })
        elif res.status == "cancelled":
            # Suggest unblocking units that may have been blocked
            for unit in units:
                conflicts.append({
                    "unit": unit,
                    "start": res.start,
                    "end": res.end,
                    "reason": f"{main_unit} cancelled {res.start} → {res.end}, Unblock {block_start} → {block_end} for {unit}"
                })
    return conflicts


def send_discord(webhook_url: str, content: str):
    """Post a message to a Discord channel via its incoming webhook.

    Discord caps a single message at 2000 chars, so long conflict lists are
    split across multiple posts.
    """
    if not webhook_url:
        print("⚠️  No DISCORD_WEBHOOK_URL set -- skipping Discord notification.")
        return

    chunks = []
    remaining = content
    while remaining:
        if len(remaining) <= 2000:
            chunks.append(remaining)
            break
        # split on the last newline within the limit so we don't cut a line
        cut = remaining.rfind("\n", 0, 2000)
        if cut <= 0:
            cut = 2000
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    for chunk in chunks:
        try:
            resp = requests.post(webhook_url, json={"content": chunk}, timeout=30)
            if resp.status_code in (200, 204):
                print("✅ Discord notification sent.")
            else:
                print(f"❌ Discord returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"❌ Failed to send Discord notification: {e}")


def send_email_sendgrid(subject: str, body: str, to_email: str, from_email: str, api_key: str):
    message = Mail(
        from_email=from_email,
        to_emails=to_email,
        subject=subject,
        plain_text_content=body
    )
    try:
        ssl._create_default_https_context = ssl._create_unverified_context
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        print(f"✅ Email sent: {response.status_code}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


def load_previous_state(filename: str) -> dict:
    """Load the previously-saved reservation snapshot, or {} on the first run.

    The file is committed to the repo, so a normal Actions checkout makes it
    available locally. Missing/corrupt file => empty state (treated as first run).
    """
    if not os.path.exists(filename):
        print(f"ℹ️  No previous state file ({filename}); treating this as the first run.")
        return {}
    try:
        with open(filename) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  Could not read {filename}: {e}; treating as empty state.")
        return {}


def build_snapshot(bookings: List[Booking]) -> dict:
    """Current *booked* reservations as {listing: {uid: {start, end, summary}}}.

    Only 'booked' events with a UID are tracked — those are the guest
    reservations whose disappearance means a cancellation.
    """
    snapshot: Dict[str, Dict[str, dict]] = {}
    for b in bookings:
        if b.status != "booked" or not b.uid:
            continue
        snapshot.setdefault(b.listing, {})[b.uid] = {
            "start": b.start.isoformat(),
            "end": b.end.isoformat(),
            "summary": b.summary,
        }
    return snapshot


def detect_cancellations(previous: dict, current: dict) -> List[dict]:
    """Reservations present last run but gone now, whose stay is still upcoming.

    A booking that simply passed its checkout date also 'disappears' from the
    feed, so we only flag a missing UID when its end date is still in the
    future — otherwise it just aged out normally.
    """
    today = date.today()
    cancellations = []
    for listing, prev_res in previous.items():
        curr_res = current.get(listing, {})
        for uid, info in prev_res.items():
            if uid in curr_res:
                continue  # still on the calendar
            try:
                end = date.fromisoformat(info["end"])
            except (KeyError, ValueError):
                continue  # missing/garbled end -> can't confirm, skip
            if end <= today:
                continue  # stay already over: aged out, not a cancellation
            cancellations.append({
                "listing": listing,
                "start": info.get("start"),
                "end": info.get("end"),
                "summary": info.get("summary", ""),
            })
    return cancellations


def commit_state_to_github(filename: str):
    """Commit the snapshot file to the repo so the next run can diff against it."""
    if not GITHUB_TOKEN:
        print("⚠️  No GH_JADA_TOKEN set -- cannot persist state to GitHub.")
        return
    api_url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    with open(filename, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")
    sha = requests.get(api_url, headers=headers).json().get("sha", "")
    payload = {"message": f"Update {filename}", "content": content, "branch": GITHUB_BRANCH}
    if sha:
        payload["sha"] = sha
    resp = requests.put(api_url, headers=headers, json=payload)
    if resp.status_code in (200, 201):
        print(f"💾 State committed to GitHub: {filename}")
    else:
        print(f"❌ Failed to commit state: {resp.status_code} {resp.text[:200]}")


def save_state(filename: str, snapshot: dict):
    """Write the fresh snapshot locally, and commit it unless this is a dry run."""
    with open(filename, "w") as f:
        json.dump(snapshot, f, indent=2, sort_keys=True)
    print(f"💾 Wrote {filename} locally.")
    if DRY_RUN:
        print("🧪 DRY_RUN: not committing state to GitHub.")
        return
    commit_state_to_github(filename)


if __name__ == "__main__":
    if DRY_RUN:
        print("🧪 DRY_RUN enabled: no email/Discord will be sent and state will not be committed.\n")
    reservations = fetch_all_listings(LISTINGS)
    conflicts = []
    body = ''
    print("=== All Bookings ===")
    for b in sorted(reservations, key=lambda x: (x.start, x.listing)):
        print(f"{b.listing:20} {b.start} → {b.end}  [{b.status}]  {b.summary}")

    print("=== Conflicts ===")
    for k,v in LISTINGS.items():
        print(f"Checking conflicts for {k} ...")
        conflicts = conflicts + (detect_conflicts(reservations, k, v['shared_units']))

    if conflicts:
        discord_lines = []
        for c in conflicts:
            print(f"{c['reason']}")
            body = body + f"{c['reason']}\n\n"
            discord_lines.append(f"- {c['reason']}")
        body = "RENTAL CALENDAR BLOCK VERIFICATION\n\n" + body
        discord_body = (
            "@here 📅 **RENTAL CALENDAR BLOCK VERIFICATION**\n\n"
            + "\n".join(discord_lines)
        )
        if DRY_RUN:
            print("🧪 DRY_RUN: would send conflict alert:\n" + discord_body)
        else:
            if SEND_EMAIL:
                send_email_sendgrid(
                    subject="Calendar Booking Conflict Alert",
                    body=body,
                    to_email="realtyjada@gmail.com",
                    from_email="report@wildfire.paloaltonetworks.com",
                    api_key=os.getenv("SENDGRID_APIKEY")
                )
            if SEND_DISCORD:
                send_discord(os.getenv("DISCORD_WEBHOOK_URL", ""), discord_body)
        print(body)
    else:
        print("No conflicts detected 🎉")

    # ---- Cancellation detection (independent of conflict detection above) ----
    print("=== Cancellations ===")
    previous_state = load_previous_state(STATE_FILE)
    current_snapshot = build_snapshot(reservations)

    if not previous_state:
        print("ℹ️  First run (empty state): seeding snapshot, skipping cancellation check.")
    else:
        cancellations = detect_cancellations(previous_state, current_snapshot)
        if cancellations:
            cancel_lines = []
            for c in cancellations:
                shared = LISTINGS.get(c["listing"], {}).get("shared_units", [])
                line = f"{c['listing']} reservation {c['start']} → {c['end']} was cancelled/removed."
                if shared:
                    line += f" Consider unblocking those dates on: {', '.join(shared)}."
                print(f"🔴 {line}")
                cancel_lines.append(line)
            discord_body = (
                "@here 🔴 **RESERVATION CANCELLATION DETECTED**\n\n"
                + "\n".join(f"- {l}" for l in cancel_lines)
            )
            email_body = "RESERVATION CANCELLATION DETECTED\n\n" + "\n\n".join(cancel_lines)
            if DRY_RUN:
                print("🧪 DRY_RUN: would send cancellation alert:\n" + discord_body)
            else:
                if SEND_EMAIL:
                    send_email_sendgrid(
                        subject="Reservation Cancellation Alert",
                        body=email_body,
                        to_email="realtyjada@gmail.com",
                        from_email="report@wildfire.paloaltonetworks.com",
                        api_key=os.getenv("SENDGRID_APIKEY")
                    )
                if SEND_DISCORD:
                    send_discord(os.getenv("DISCORD_WEBHOOK_URL", ""), discord_body)
        else:
            print("No cancellations detected 🎉")

    # Persist the fresh snapshot for the next run's diff.
    save_state(STATE_FILE, current_snapshot)

