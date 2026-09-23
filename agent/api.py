import json
import sys
import httpx

from agent.config import (
    ACCOUNTS_CACHE_FILE,
    CATEGORIES_CACHE_FILE,
    CATEGORY_SAMPLES_CACHE_FILE,
    DATA_DIR,
    SURE_API_KEY,
    SURE_API_URL,
)


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
            print(
                f"Warning: Failed to fetch sample transaction for category '{cat_name}': {e}",
                file=sys.stderr,
            )
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
    CATEGORY_SAMPLES_CACHE_FILE.write_text(
        json.dumps(category_samples, indent=2), encoding="utf-8"
    )

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


def post_transaction(payload: dict):
    headers = {
        "X-Api-Key": SURE_API_KEY,
        "Content-Type": "application/json",
    }
    with httpx.Client(base_url=SURE_API_URL) as client:
        response = client.post("transactions", json=payload, headers=headers, timeout=10)
        return response.json()
