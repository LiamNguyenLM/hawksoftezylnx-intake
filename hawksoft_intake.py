from dotenv import load_dotenv
load_dotenv()

import os
import gspread
import requests
from datetime import datetime
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

HAWKSOFT_USERNAME = os.environ.get("HAWKSOFT_USERNAME", "")
HAWKSOFT_PASSWORD = os.environ.get("HAWKSOFT_PASSWORD", "")
HAWKSOFT_AGENCY_ID = os.environ.get("HAWKSOFT_AGENCY_ID", "")
EZLYNX_API_URL = os.environ.get("EZLYNX_API_URL", "").rstrip("/") + "/"
EZLYNX_APP_SECRET = os.environ.get("EZLYNX_APP_SECRET", "")
EZLYNX_ACCOUNT_USERNAME = os.environ.get("EZLYNX_ACCOUNT_USERNAME", "")
EZLYNX_ACCOUNT_PASSWORD = os.environ.get("EZLYNX_ACCOUNT_PASSWORD", "")
SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "hawksoft")
HAWKSOFT_BASE_URL = "https://integration.hawksoft.app"


def get_sheet():
    creds = Credentials.from_service_account_file(
        "google_credentials.json", scopes=SCOPES
    )
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1


def get_ezlynx_token():
    response = requests.get(
        f"{EZLYNX_API_URL}authenticate",
        headers={
            "EZAppSecret": EZLYNX_APP_SECRET,
            "AccountUsername": EZLYNX_ACCOUNT_USERNAME
        },
        params={"password": EZLYNX_ACCOUNT_PASSWORD}
    )
    if response.status_code == 200:
        return response.text.strip().strip('"')
    return None


def create_hawksoft_client(row):
    first = row.get("First Name", "").strip()
    last = row.get("Last Name", "").strip()

    contacts = []
    if row.get("Email", "").strip():
        contacts.append({"Type": "HomeEmail", "Value": row["Email"].strip()})
    if row.get("Phone", "").strip():
        contacts.append({"Type": "CellPhone", "Value": row["Phone"].strip()})

    person = {"FirstName": first, "LastName": last, "MainContactType": "First"}
    if contacts:
        person["Contacts"] = contacts

    body = {
        "People": [person],
        "Log": {
            "Channel": 29,
            "Note": f"Prospect created via intake form on {datetime.now().strftime('%Y-%m-%d')}",
            "TS": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        },
        "Status": "Prospect"
    }

    if row.get("Address", "").strip():
        body["MailingAddress"] = {
            "Address1": row.get("Address", "").strip(),
            "City": row.get("City", "").strip(),
            "State": row.get("State", "TX").strip(),
            "Zip": row.get("ZIP", "").strip()
        }

    return requests.post(
        f"{HAWKSOFT_BASE_URL}/vendor/agency/{HAWKSOFT_AGENCY_ID}/client?version=4.0",
        json=body,
        auth=(HAWKSOFT_USERNAME, HAWKSOFT_PASSWORD)
    )


def create_ezlynx_applicant(row, ez_token):
    first = row.get("First Name", "").strip()
    last = row.get("Last Name", "").strip()

    body = {
        "FirstName": first,
        "LastName": last,
        "CurrentAddress": {
            "AddressLine1": row.get("Address", "").strip(),
            "City": row.get("City", "").strip(),
            "State": row.get("State", "TX").strip(),
            "Zip": row.get("ZIP", "").strip()
        },
        "CellPhone": row.get("Phone", "").strip(),
        "Email": row.get("Email", "").strip()
    }

    return requests.post(
        f"{EZLYNX_API_URL}Applicant/v2/",
        json=body,
        headers={
            "Content-Type": "application/json",
            "EZAppSecret": EZLYNX_APP_SECRET,
            "EZToken": ez_token,
            "AccountUsername": EZLYNX_ACCOUNT_USERNAME
        }
    )


def process_intake():
    print("Connecting to Google Sheets...")
    sheet = get_sheet()
    all_rows = sheet.get_all_records()

    headers = sheet.row_values(1)
    processed_col = headers.index("Processed") + 1
    hs_num_col = headers.index("HawkSoft Client #") + 1
    ez_id_col = headers.index("EZLynx ID") + 1
    notes_col = headers.index("Notes") + 1

    pending = [
        (i + 2, row) for i, row in enumerate(all_rows)
        if not row.get("Processed", "").strip()
    ]

    if not pending:
        print("No pending rows.")
        return

    print(f"Found {len(pending)} pending rows.")
    print("Getting EZLynx token...")
    ez_token = get_ezlynx_token()
    if not ez_token:
        print("Warning: Could not get EZLynx token. EZLynx creation will be skipped.")

    for row_num, row in pending:
        name = f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip()
        print(f"Processing: {name}...")
        notes = []
        hs_num = ""
        ez_id = ""

        # HawkSoft
        try:
            hs_response = create_hawksoft_client(row)
            if hs_response.status_code == 200:
                hs_num = str(hs_response.json().get("clientNumber", ""))
                notes.append("HawkSoft: Success")
                print(f"  HawkSoft: Client #{hs_num}")
            else:
                notes.append(f"HawkSoft Error {hs_response.status_code}")
                print(f"  HawkSoft failed: {hs_response.status_code}")
        except Exception as e:
            notes.append(f"HawkSoft Exception: {str(e)[:100]}")
            print(f"  HawkSoft exception: {e}")

        # EZLynx
        if ez_token:
            try:
                ez_response = create_ezlynx_applicant(row, ez_token)
                if ez_response.status_code == 201:
                    ez_id = str(ez_response.json())
                    notes.append("EZLynx: Success")
                    print(f"  EZLynx: Applicant #{ez_id}")
                else:
                    notes.append(f"EZLynx Error {ez_response.status_code}")
                    print(f"  EZLynx failed: {ez_response.status_code}")
            except Exception as e:
                notes.append(f"EZLynx Exception: {str(e)[:100]}")
                print(f"  EZLynx exception: {e}")
        else:
            notes.append("EZLynx: Skipped (no token)")

        # Update sheet
        sheet.update_cell(row_num, processed_col, datetime.now().strftime("%Y-%m-%d %H:%M"))
        sheet.update_cell(row_num, hs_num_col, hs_num)
        sheet.update_cell(row_num, ez_id_col, ez_id)
        sheet.update_cell(row_num, notes_col, " | ".join(notes))

    print("Done.")


if __name__ == "__main__":
    process_intake()
