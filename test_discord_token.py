#!/usr/bin/env python3
"""
Quick test script to verify your Discord token works.
Run this before trying to start the full system.
"""

import os
from dotenv import load_dotenv
import requests

# Load .env file
load_dotenv()

token = os.getenv("DISCORD_USER_TOKEN")

if not token:
    print("❌ No DISCORD_USER_TOKEN found in .env file!")
    print("\nMake sure your .env file has:")
    print("DISCORD_USER_TOKEN=your_token_here")
    exit(1)

print(f"Testing token: {token[:20]}...{token[-10:]}")
print()

# Test the token
headers = {
    "Authorization": token
}

try:
    response = requests.get("https://discord.com/api/v9/users/@me", headers=headers)

    if response.status_code == 200:
        user = response.json()
        username = user.get('username', 'Unknown')
        user_id = user.get('id', 'Unknown')

        print("✅ Token is VALID!")
        print(f"   Logged in as: {username}")
        print(f"   User ID: {user_id}")
        print()
        print("You can now run the trading system:")
        print("   python -m src.orchestrator.main")

    else:
        print("❌ Token is INVALID!")
        print(f"   Status: {response.status_code}")
        print(f"   Error: {response.text}")
        print()
        print("Common fixes:")
        print("1. Get a fresh token (see get_token_helper.md)")
        print("2. Make sure you copied the entire token")
        print("3. No quotes around the token in .env")
        print("4. Try changing your Discord password for a new token")

except Exception as e:
    print(f"❌ Error testing token: {e}")
    print()
    print("Make sure you have 'requests' installed:")
    print("   pip install requests")
