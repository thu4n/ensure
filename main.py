#!/usr/bin/env -S uv run --script

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import httpx
from mlx_lm import load, generate

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / ".data"
ACCOUNTS_CACHE_FILE = DATA_DIR / "accounts.json"
CATEGORIES_CACHE_FILE = DATA_DIR / "categories.json"
CATEGORY_SAMPLES_CACHE_FILE = DATA_DIR / "category_samples.json"

SURE_API_URL = os.getenv("SURE_API_URL", "http://sure-web.self-host.orb.local/api/v1/")
SURE_API_KEY = os.getenv("SURE_API_KEY", "")
MODEL_ID = "mlx-community/Llama-3.2-3B-Instruct-4bit"
DEFAULT_ACCOUNT_ID = os.getenv("DEFAULT_ACCOUNT_ID", "81cb8465-1cad-47d5-8061-b8e4baa954db")  # Wallet
DEFAULT_CATEGORY_ID = "adaac5f4-5de7-4d2b-b3d9-45079ebf6208"  # Main meal

EXTRACTION_SCHEMA = {
    "account": "string (must match one of the available accounts name exactly)",
    "amount": "number (positive numeric value, convert 45k -> 45000)",
    "name": "string (short title/merchant, e.g. 'Coffee', 'Grab Ride', 'Banh Mi')",
    "currency": "string (e.g. VND, USD, EUR)",
    "date": "string (YYYY-MM-DD format)",
    "category": "string (must match one of the available categories exactly)",
}


def fetch_accounts(client: httpx.Client, headers: dict) -> dict:
    account_map = {}
    page = 1
    while True:
        response = client.get(f"accounts?page={page}&per_page=100", headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        for c in data.get("accounts", []):
            account_map[c["name"]] = c["id"]

        pagination = data.get("pagination", {})
        if page >= pagination.get("total_pages", 1):
            break
        page += 1
    return account_map


def fetch_categories(client: httpx.Client, headers: dict) -> dict:
    category_map = {}
    page = 1
    while True:
        response = client.get(f"categories?page={page}&per_page=100", headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        for c in data.get("categories", []):
            category_map[c["name"]] = c["id"]

        pagination = data.get("pagination", {})
        if page >= pagination.get("total_pages", 1):
            break
        page += 1
    return category_map


def fetch_category_samples(client: httpx.Client, headers: dict, category_map: dict) -> dict:
    samples = {}
    for cat_name, cat_id in category_map.items():
        try:
            response = client.get(
                "transactions",
                params={"category_id": cat_id, "per_page": 1},
                headers=headers,
                timeout=10,
            )
            if response.status_code == 200:
                txs = response.json().get("transactions", [])
                if txs:
                    tx = txs[0]
                    samples[cat_name] = {
                        "name": tx.get("name", ""),
                        "notes": tx.get("notes", "") or "",
                    }
                else:
                    samples[cat_name] = None
            else:
                samples[cat_name] = None
        except Exception as e:
            print(f"Warning: Failed to fetch sample transaction for category '{cat_name}': {e}", file=sys.stderr)
            samples[cat_name] = None
    return samples


def fetch_and_cache_all() -> tuple[dict, dict, dict]:
    headers = {
        "X-Api-Key": SURE_API_KEY,
    }
    with httpx.Client(base_url=SURE_API_URL) as client:
        print("Fetching categories and accounts from API...")
        category_map = fetch_categories(client, headers)
        account_map = fetch_accounts(client, headers)
        print(f"Fetching sample transactions for {len(category_map)} categories...")
        category_samples = fetch_category_samples(client, headers, category_map)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CATEGORIES_CACHE_FILE.write_text(json.dumps(category_map, indent=2), encoding="utf-8")
    ACCOUNTS_CACHE_FILE.write_text(json.dumps(account_map, indent=2), encoding="utf-8")
    CATEGORY_SAMPLES_CACHE_FILE.write_text(json.dumps(category_samples, indent=2), encoding="utf-8")

    return category_map, account_map, category_samples


def load_data(force_update: bool = False) -> tuple[dict, dict, dict]:
    cache_exists = (
        CATEGORIES_CACHE_FILE.exists()
        and ACCOUNTS_CACHE_FILE.exists()
        and CATEGORY_SAMPLES_CACHE_FILE.exists()
    )

    if not force_update and cache_exists:
        try:
            category_map = json.loads(CATEGORIES_CACHE_FILE.read_text(encoding="utf-8"))
            account_map = json.loads(ACCOUNTS_CACHE_FILE.read_text(encoding="utf-8"))
            category_samples = json.loads(CATEGORY_SAMPLES_CACHE_FILE.read_text(encoding="utf-8"))
            print(f"Loaded {len(category_map)} categories and {len(account_map)} accounts from cache.")
            return category_map, account_map, category_samples
        except Exception as e:
            print(f"Cache read error: {e}. Re-fetching from API...", file=sys.stderr)

    if force_update:
        print("Updating local cache from API (--update specified)...")
    else:
        print("Local cache not found. Fetching initial data from API...")

    category_map, account_map, category_samples = fetch_and_cache_all()
    print(
        f"Saved {len(category_map)} categories, {len(account_map)} accounts, "
        f"and {len(category_samples)} category samples to local cache."
    )
    return category_map, account_map, category_samples


def extract_transaction_details(
    user_input: str,
    category_map: dict,
    account_map: dict,
    category_samples: dict = None,
) -> dict:
    model, tokenizer = load(MODEL_ID)
    today = datetime.now().strftime("%Y-%m-%d")

    category_samples = category_samples or {}
    category_lines = []
    for name in category_map.keys():
        sample = category_samples.get(name)
        sample_name = None
        if isinstance(sample, dict):
            sample_name = sample.get("name")
        elif isinstance(sample, str):
            sample_name = sample

        if sample_name:
            clean_sample = " ".join(sample_name.split())
            if len(clean_sample) > 50:
                clean_sample = clean_sample[:47] + "..."
            category_lines.append(f'- "{name}" (example: "{clean_sample}")')
        else:
            category_lines.append(f'- "{name}"')

    available_categories = "\n".join(category_lines)
    available_accounts = ", ".join(f'"{name}"' for name in account_map.keys())

    messages = [
        {
            "role": "system",
            "content": (
                "You are a finance parsing assistant. Extract transaction details from user input into a single raw JSON object matching this schema:\n"
                f"{json.dumps(EXTRACTION_SCHEMA, indent=2)}\n\n"
                f"Today is {today}. If the user doesn't state a date, use today's date.\n\n"
                f"Available categories:\n{available_categories}\n\n"
                f"Available accounts:\n[{available_accounts}]\n\n"
                "Instruction for category:\n"
                "- Choose the single best fitting category from the Available categories list for the 'category' field.\n"
                "- Use the provided example past transactions to understand each category's context and meaning.\n"
                "- The 'category' field in your JSON output must be ONLY the category name exactly (do not include the example in the category value).\n\n"
                "Instruction for accounts:\n"
                "- Choose from the Available accounts list. If the user specifies none, default to Wallet.\n\n"
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


def resolve_category_id(category_name: str, category_map: dict) -> str:
    if not category_name:
        return DEFAULT_CATEGORY_ID
    # 1. Exact match
    if category_name in category_map:
        return category_map[category_name]
    # 2. Case-insensitive match
    lower_map = {k.lower(): v for k, v in category_map.items()}
    if category_name.lower() in lower_map:
        return lower_map[category_name.lower()]
    # 3. Singular / plural variation
    norm = category_name.lower().rstrip("s")
    for k, v in category_map.items():
        if k.lower().rstrip("s") == norm:
            return v
    # 4. Partial / substring match
    for k, v in category_map.items():
        if category_name.lower() in k.lower() or k.lower() in category_name.lower():
            return v
    return DEFAULT_CATEGORY_ID


def resolve_account_id(account_name: str, account_map: dict) -> str:
    if not account_name:
        return DEFAULT_ACCOUNT_ID
    if account_name in account_map:
        return account_map[account_name]
    lower_map = {k.lower(): v for k, v in account_map.items()}
    if account_name.lower() in lower_map:
        return lower_map[account_name.lower()]
    for k, v in account_map.items():
        if account_name.lower() in k.lower() or k.lower() in account_name.lower():
            return v
    return DEFAULT_ACCOUNT_ID


def build_payload(parsed: dict, category_map: dict, account_map: dict) -> dict:
    category_id = resolve_category_id(parsed.get("category", ""), category_map)
    account_id = resolve_account_id(parsed.get("account", ""), account_map)
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
    raw_args = sys.argv[1:]
    update_flag = False
    filtered_args = []

    for arg in raw_args:
        if arg in ("--update", "-u"):
            update_flag = True
        else:
            filtered_args.append(arg)

    if not update_flag and not filtered_args:
        print('Usage: ispent [--update] "<expense sentence>"')
        sys.exit(1)

    category_map, account_map, category_samples = load_data(force_update=update_flag)

    raw_input = " ".join(filtered_args).strip()
    if not raw_input:
        if update_flag:
            print("Cache updated successfully.")
            return
        else:
            print('Usage: ispent [--update] "<expense sentence>"')
            sys.exit(1)

    print(f"Parsing: \"{raw_input}\"...")

    try:
        parsed = extract_transaction_details(raw_input, category_map, account_map, category_samples)
        print(f"\nParsed by LLM:\n{json.dumps(parsed, indent=2)}")
        payload = build_payload(parsed, category_map, account_map)

        print("\nGenerated API Payload:")
        print(json.dumps(payload, indent=2))

        res = post_transaction(payload)
        print(f"\nResponse: {res}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
