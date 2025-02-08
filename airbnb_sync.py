import requests
import ics
import base64
import os

# -------------------- CONFIGURATION --------------------
AIRBNB_ICS_URL = os.getenv("AIRBNB_ICS_URL")
GITHUB_USERNAME = "j4sonxp"
GITHUB_REPO = "airbnb-calendar"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
FILE_NAME = "filtered_airbnb.ics"
GITHUB_BRANCH = "main"  # Change if using a different branch
# ------------------------------------------------------

def fetch_airbnb_calendar():
    """Fetch and parse Airbnb ICS calendar."""
    response = requests.get(AIRBNB_ICS_URL)
    if response.status_code != 200:
        print("Failed to fetch Airbnb ICS file")
        return []

    calendar = ics.Calendar(response.text)
    return [event for event in calendar.events if "Reserved" in event.name]

def generate_filtered_ics():
    """Create a new ICS file with only 'Reserved' events."""
    reservations = fetch_airbnb_calendar()
    
    if not reservations:
        print("No 'Reserved' events found. Skipping ICS file creation.")
        return False

    new_calendar = ics.Calendar()
    for event in reservations:
        new_calendar.events.add(event)

    with open(FILE_NAME, "w") as f:
        f.writelines(new_calendar)

    print(f"Filtered ICS file saved: {FILE_NAME}")
    return True

def upload_to_github():
    """Upload the filtered .ics file to GitHub repository."""
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{FILE_NAME}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    # Read file and encode to base64
    with open(FILE_NAME, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    # Check if file already exists
    response = requests.get(url, headers=headers)
    sha = response.json().get("sha", "")

    # Prepare payload
    payload = {
        "message": "Update Airbnb filtered ICS",
        "content": content,
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha  # Required for updating an existing file

    # Upload file
    response = requests.put(url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        public_url = f"https://raw.githubusercontent.com/{GITHUB_USERNAME}/{GITHUB_REPO}/{GITHUB_BRANCH}/{FILE_NAME}"
        print(f"Uploaded to GitHub: {public_url}")
        return public_url
    else:
        print(f"GitHub upload failed: {response.json()}")
        return None

if __name__ == "__main__":
    if generate_filtered_ics():
        upload_to_github()

