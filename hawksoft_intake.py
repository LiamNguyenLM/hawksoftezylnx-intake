from dotenv import load_dotenv
load_dotenv()

import os
import gspread
import requests
import uuid
from datetime import datetime
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

HAWKSOFT_USERNAME = os.environ.get("HAWKSOFT_USERNAME", "")
HAWKSOFT_PASSWORD = os.environ.get("HAWKSOFT_PASSWORD", "")
HAWKSOFT_AGENCY_ID = os.environ.get("HAWKSOFT_AGENCY_ID", "")
SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "New Prospect Intake")
BASE_URL = "https://integration.hawksoft.app"


def get_sheet():
    creds = Credentials.from_service_account_file(
        "google_credentials.json", scopes=SCOPES
    )
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
    return sheet


def split_name(full_name):
    parts = full_name.strip().split(" ", 1)
    first = parts[0] if len(parts) > 0 else ""
    last = parts[1] if len(parts) > 1 else ""
    return first, last


def create_client(row):
    first_name, last_name = split_name(row.get("First Name", "") + " " + row.get("Last Name", ""))

    # If sheet has separate first/last columns, use those directly
    if row.get("First Name") and row.get("Last Name"):
        first_name = row["First Name"].strip()
        last_name = row["Last Name"].strip()

    contacts = []
    if row.get("Email", "").strip():
        contacts.append({"Type": "HomeEmail", "Value": row["Email"].strip()})
    if row.get("Phone", "").strip():
        contacts.append({"Type": "CellPhone", "Value": row["Phone"].strip()})

    person = {
        "FirstName": first_name,
        "LastName": last_name,
        "MainContactType": "First"
    }
    if contacts:
        person["Contacts"] = contacts

    body = {
        "People": [person],
        "Log": {
            "Channel": 29,
            "Note": f"Prospect created via email intake on {datetime.now().strftime('%Y-%m-%d')}",
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

    url = f"{BASE_URL}/vendor/agency/{HAWKSOFT_AGENCY_ID}/client?version=4.0"
    response = requests.post(
        url,
        json=body,
        auth=(HAWKSOFT_USERNAME, HAWKSOFT_PASSWORD)
    )

    return response


def process_intake():
    print("Connecting to Google Sheets...")
    sheet = get_sheet()
    all_rows = sheet.get_all_records()

    # Find column indexes (1-based for gspread)
    headers = sheet.row_values(1)
    processed_col = headers.index("Processed") + 1
    client_num_col = headers.index("Client Number") + 1
    notes_col = headers.index("Notes") + 1

    pending = [
        (i + 2, row) for i, row in enumerate(all_rows)
        if not row.get("Processed", "").strip()
    ]

    if not pending:
        print("No pending rows to process.")
        return

    print(f"Found {len(pending)} pending rows.")

    for row_num, row in pending:
        name = f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip()
        print(f"Processing: {name}...")

        try:
            response = create_client(row)

            if response.status_code == 200:
                client_number = response.json().get("clientNumber", "")
                sheet.update_cell(row_num, processed_col, datetime.now().strftime("%Y-%m-%d %H:%M"))
                sheet.update_cell(row_num, client_num_col, str(client_number))
                sheet.update_cell(row_num, notes_col, "Success")
                print(f"  Created — HawkSoft Client #{client_number}")
            else:
                error_msg = f"Error {response.status_code}: {response.text[:200]}"
                sheet.update_cell(row_num, notes_col, error_msg)
                print(f"  Failed — {error_msg}")

        except Exception as e:
            sheet.update_cell(row_num, notes_col, f"Exception: {str(e)[:200]}")
            print(f"  Exception: {e}")

    print("Done.")


if __name__ == "__main__":
    process_intake()
