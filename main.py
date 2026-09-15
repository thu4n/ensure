#!/usr/bin/env -S uv run --script

import json
import os
import re
import sys
from dotenv import load_dotenv
from datetime import datetime
import httpx
from mlx_lm import load, generate

load_dotenv()

SURE_API_URL = os.getenv("SURE_API_URL", "http://sure-web.self-host.orb.local/api/v1/")
SURE_API_KEY = os.getenv("SURE_API_KEY", "")
MODEL_ID = "mlx-community/Llama-3.2-3B-Instruct-4bit"
DEFAULT_ACCOUNT_ID = os.getenv("DEFAULT_ACCOUNT_ID", "81cb8465-1cad-47d5-8061-b8e4baa954db") # Wallet
DEFAULT_CATEGORY_ID = "adaac5f4-5de7-4d2b-b3d9-45079ebf6208" # Main meal
CATEGORY_MAP = {}
ACCOUNT_MAP = {}
EXTRACTION_SCHEMA = {
    "account": "string (must match one of the available accounts name exactly)",
    "amount": "number (positive numeric value, convert 45k -> 45000)",
    "name": "string (short title/merchant, e.g. 'Coffee', 'Grab Ride', 'Banh Mi')",
    "currency": "string (e.g. VND, USD, EUR)",
    "date": "string (YYYY-MM-DD format)",
    "category": "string (must match one of the available categories exactly)"
}

def get_accounts()-> dict:
    headers = {
        "X-Api-Key": SURE_API_KEY,
    }
    account_map = {}
    page = 1
    with httpx.Client(base_url=SURE_API_URL) as client:
        while True:
            response = client.get(f"accounts?page={page}&per_page=100", headers=headers, timeout=10)
            data = response.json()
            for c in data.get("accounts", []):
                account_map[c["name"]] = c["id"]

            pagination = data.get("pagination", {})
            if page >= pagination.get("total_pages", 1):
                break
            page += 1
    return account_map

def get_categories() -> dict:
    headers = {
        "X-Api-Key": SURE_API_KEY,
    }
    category_map = {}
    page = 1
    with httpx.Client(base_url=SURE_API_URL) as client:
        while True:
            response = client.get(f"categories?page={page}&per_page=100", headers=headers, timeout=10)
            data = response.json()
            for c in data.get("categories", []):
                category_map[c["name"]] = c["id"]

            pagination = data.get("pagination", {})
            if page >= pagination.get("total_pages", 1):
                break
            page += 1
    return category_map

def extract_transaction_details(user_input: str, category_map: dict, account_map: dict) -> dict:
    model, tokenizer = load(MODEL_ID)
    today = datetime.now().strftime("%Y-%m-%d")
    available_categories = ", ".join(f'"{name}"' for name in category_map.keys())
    available_accounts = ", ".join(f'"{name}"' for name in account_map.keys())
    print(available_accounts)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a finance parsing assistant. Extract transaction details from user input into a single raw JSON object matching this schema:\n"
                f"{json.dumps(EXTRACTION_SCHEMA, indent=2)}\n\n"
                f"Today is {today}. If the user doesn't state a date, use today's date.\n\n"
                f"Available categories:\n[{available_categories}]\n"
                f"Available accounts:\n[{available_accounts}]\n"
                "Instruction for category: Choose the single best fitting category from the Available categories list for the 'category' field. Same for accounts, if the user specify none, default to Wallet.\n"
                "Return ONLY valid raw JSON. No explanations, no markdown blocks."
            ),
        },
        {"role": "user", "content": user_input},
    ]

    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    raw_output = generate(model, tokenizer, prompt=prompt, max_tokens=200, verbose=False)

    match = re.search(r"\{.*\}", raw_output, re.DOTALL)
    if not match:
        raise ValueError(f"Failed to extract JSON from model output:\n{raw_output}")

    return json.loads(match.group(0))

def build_payload(parsed: dict, category_map: dict, account_map: dict) -> dict:
    category_name = parsed.get("category")
    account_name = parsed.get("account")
    category_id = category_map.get(category_name, DEFAULT_CATEGORY_ID)
    account_id = account_map.get(account_name, DEFAULT_ACCOUNT_ID)
    return {
        "transaction": {
            "account_id": account_id,
            "date": parsed.get("date", datetime.now().strftime("%Y-%m-%d")),
            "amount": parsed.get("amount", 0),
            "name": parsed.get("name", "Unknown Expense"),
            "description": parsed.get("description", parsed.get("name", "")),
            "notes": parsed.get("notes", ""),
            "currency": parsed.get("currency", "VND"),
            "category_id": category_id,
            "merchant_id": None,
            "tag_ids": [],
            "user_modified": True,
        }
    }

def post_transaction(payload: dict):
    headers = {
        "X-Api-Key": SURE_API_KEY,
        "Content-Type": "application/json",
    }
    with httpx.Client(base_url=SURE_API_URL) as client:
        response = client.post("transactions", json=payload, headers=headers, timeout=10)
        return response.json()

def main():
    if len(sys.argv) < 2:
        print('Usage: ispent "<expense sentence>"')
        sys.exit(1)
    CATEGORY_MAP = get_categories()
    ACCOUNT_MAP = get_accounts()
    print(f"Loaded {len(CATEGORY_MAP)} categories from API.")
    print(f"Loaded {len(ACCOUNT_MAP)} accounts from API.")
    raw_input = " ".join(sys.argv[1:])
    print(f"Parsing: \"{raw_input}\"...")

    try:
        parsed = extract_transaction_details(raw_input, CATEGORY_MAP, ACCOUNT_MAP)
        print(f"\nParsed by LLM:\n{json.dumps(parsed, indent=2)}")
        payload = build_payload(parsed, CATEGORY_MAP, ACCOUNT_MAP)

        print("\nGenerated API Payload:")
        print(json.dumps(payload, indent=2))

        # res = post_transaction(payload)
        # print(f"\nResponse: {res}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
