import requests
import icalendar
import ssl
import os
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


if __name__ == "__main__":
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
        if SEND_EMAIL:
            send_email_sendgrid(
                subject="Calendar Booking Conflict Alert",
                body=body,
                to_email="realtyjada@gmail.com",
                from_email="report@wildfire.paloaltonetworks.com",
                api_key=os.getenv("SENDGRID_APIKEY")
            )
        if SEND_DISCORD:
            discord_body = (
                "@here 📅 **RENTAL CALENDAR BLOCK VERIFICATION**\n\n"
                + "\n".join(discord_lines)
            )
            send_discord(os.getenv("DISCORD_WEBHOOK_URL", ""), discord_body)
        print(body)
    else:
        print("No conflicts detected 🎉")

