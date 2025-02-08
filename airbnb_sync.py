import requests
import ics
import base64
import os

Bellomy_Calenders = [
    {'ics_url': 'https://www.airbnb.com/calendar/ical/929199535851759140.ics?s=fb189684659d74538e93c7d89ecbad51',
     'ics_filename': 'backunit_airbnb.ics'},
    {'ics_url': 'https://www.airbnb.com/calendar/ical/27507605.ics?s=a8b9bcc45e6790606431bea118b35f6b',
     'ics_filename': 'frontunit_airbnb.ics'},
    {'ics_url': 'https://www.airbnb.com/calendar/ical/1032841991458879387.ics?s=58aba5da2eff2968aaad58a64b32c802',
     'ics_filename': 'middleunit_airbnb.ics'},
    {'ics_url': 'http://www.vrbo.com/icalendar/55cd404350c44292853e559e626bcfd4.ics?nonTentative',
     'ics_filename': 'frontunit_vrbo.ics'},
    {'ics_url': 'http://www.vrbo.com/icalendar/7e15a6276db44ac4a8a65247aa5d9c0b.ics?nonTentative',
     'ics_filename': 'backunit_vrbo.ics'},
    {'ics_url': 'http://www.vrbo.com/icalendar/ba242c71cc0947d290727473ee6030e2.ics?nonTentative',
     'ics_filename': 'middleunit_vrbo.ics'},
]

# -------------------- CONFIGURATION --------------------
GITHUB_USERNAME = "j4sonxp"
GITHUB_REPO = "JadaRealty"
GITHUB_TOKEN = os.getenv("GH_JADA_TOKEN")
GITHUB_BRANCH = "main"  # Change if using a different branch
# ------------------------------------------------------

def fetch_airbnb_calendar(url):
    """Fetch and parse Airbnb ICS calendar."""
    print(f"Fetching url: \n{url}")
    response = requests.get(url)
    if response.status_code != 200:
        print("Failed to fetch ICS file")
        return []

    calendar = ics.Calendar(response.text)
    return [event for event in calendar.events if "Reserved" in event.name]


def generate_filtered_ics(url=None, filename=None):
    """Create a new ICS file with only 'Reserved' events."""
    reservations = fetch_airbnb_calendar(url)

    if not reservations:
        print("No 'Reserved' events found. Skipping ICS file creation.")
        return False

    new_calendar = ics.Calendar()
    for event in reservations:
        new_calendar.events.add(event)

    with open(filename, "w") as f:
        f.writelines(new_calendar)

    print(f"Filtered ICS file saved: {filename}")
    return True


def upload_to_github(filename=None):
    """Upload the filtered .ics file to GitHub repository."""
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    # Read file and encode to base64
    with open(filename, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    # Check if file already exists
    response = requests.get(url, headers=headers)
    sha = response.json().get("sha", "")

    # Prepare payload
    payload = {
        "message": f"Update filtered ICS {filename}",
        "content": content,
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha  # Required for updating an existing file

    # Upload file
    response = requests.put(url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        public_url = f"https://raw.githubusercontent.com/{GITHUB_USERNAME}/{GITHUB_REPO}/{GITHUB_BRANCH}/{filename}"
        print(f"Uploaded to GitHub: {public_url}")
        return public_url
    else:
        print(f"GitHub upload failed: {response.json()}")
        return None


if __name__ == "__main__":
    for unit in Bellomy_Calenders:
        if generate_filtered_ics(url=unit['ics_url'], filename=unit['ics_filename']):
            upload_to_github(filename=unit['ics_filename'])
