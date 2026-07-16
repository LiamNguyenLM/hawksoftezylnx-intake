from dotenv import load_dotenv
load_dotenv()

import os
import requests

username = os.environ.get("HAWKSOFT_USERNAME")
password = os.environ.get("HAWKSOFT_PASSWORD")

response = requests.get(
    "https://integration.hawksoft.app/vendor/agencies?version=4.0",
    auth=(username, password)
)

print("Status:", response.status_code)
print("Response:", response.text)
