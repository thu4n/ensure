import json
import sys
import httpx

from agent.config import (
    ACCOUNTS_CACHE_FILE,
    CATEGORIES_CACHE_FILE,
    CATEGORY_SAMPLES_CACHE_FILE,
    CLOUDFLARE_AUTH_TOKEN,
    CLOUDFLARE_WORKER_URL,
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
            account_map[c["name"]] = {
                "id": c["id"],
                "institution_name": c.get("institution_name"),
                "classification": c.get("classification"),
                "account_type": c.get("account_type"),
                "subtype": c.get("subtype"),
            }

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


def fetch_category_samples(
    client: httpx.Client, headers: dict, category_map: dict, max_samples: int = 3
) -> dict:
    samples = {}
    for cat_name, cat_id in category_map.items():
        try:
            response = client.get(
                "transactions",
                params={"category_id": cat_id, "per_page": 10},
                headers=headers,
                timeout=10,
            )
            if response.status_code == 200:
                txs = response.json().get("transactions", [])
                distinct_names = []
                seen_lower = set()
                for tx in txs:
                    name = (tx.get("name") or "").strip()
                    if name and name.lower() not in seen_lower:
                        seen_lower.add(name.lower())
                        distinct_names.append(name)
                        if len(distinct_names) >= max_samples:
                            break
                samples[cat_name] = distinct_names
            else:
                samples[cat_name] = []
        except Exception as e:
            print(
                f"Warning: Failed to fetch sample transactions for category '{cat_name}': {e}",
                file=sys.stderr,
            )
            samples[cat_name] = []
    return samples


def cache_history() -> tuple[dict, dict, dict]:
    headers = {
        "X-Api-Key": SURE_API_KEY,
    }
    with httpx.Client(base_url=SURE_API_URL) as client:
        print("Fetching categories and accounts from API...")
        category_map = fetch_categories(client, headers)
        account_map = fetch_accounts(client, headers)
        print(f"Caching transaction history for {len(category_map)} categories to enrich model judgment...")
        category_samples = fetch_category_samples(client, headers, category_map)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CATEGORIES_CACHE_FILE.write_text(json.dumps(category_map, indent=2), encoding="utf-8")
    ACCOUNTS_CACHE_FILE.write_text(json.dumps(account_map, indent=2), encoding="utf-8")
    CATEGORY_SAMPLES_CACHE_FILE.write_text(
        json.dumps(category_samples, indent=2), encoding="utf-8"
    )
    print(f"History cached successfully to {CATEGORY_SAMPLES_CACHE_FILE}.")
    return category_map, account_map, category_samples


def load_data(force_update: bool = False) -> tuple[dict, dict, dict]:
    category_map = {}
    account_map = {}
    category_samples = {}

    headers = {"X-Api-Key": SURE_API_KEY}

    if not force_update and CATEGORIES_CACHE_FILE.exists() and ACCOUNTS_CACHE_FILE.exists():
        try:
            category_map = json.loads(CATEGORIES_CACHE_FILE.read_text(encoding="utf-8"))
            account_map = json.loads(ACCOUNTS_CACHE_FILE.read_text(encoding="utf-8"))
            print(f"Loaded {len(category_map)} categories and {len(account_map)} accounts from cache.")
        except Exception as e:
            print(f"Cache read error: {e}. Re-fetching from API...", file=sys.stderr)

    if not category_map or not account_map:
        with httpx.Client(base_url=SURE_API_URL) as client:
            print("Fetching categories and accounts from API...")
            category_map = fetch_categories(client, headers)
            account_map = fetch_accounts(client, headers)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CATEGORIES_CACHE_FILE.write_text(json.dumps(category_map, indent=2), encoding="utf-8")
        ACCOUNTS_CACHE_FILE.write_text(json.dumps(account_map, indent=2), encoding="utf-8")

    if CATEGORY_SAMPLES_CACHE_FILE.exists():
        try:
            category_samples = json.loads(CATEGORY_SAMPLES_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            category_samples = {}

    return category_map, account_map, category_samples



def post_transaction(payload: dict):
    headers = {
        "X-Api-Key": SURE_API_KEY,
        "Content-Type": "application/json",
    }
    with httpx.Client(base_url=SURE_API_URL) as client:
        response = client.post("transactions", json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()


def fetch_pending_transactions() -> list[dict]:
    if not CLOUDFLARE_WORKER_URL:
        raise ValueError("CLOUDFLARE_WORKER_URL is not set in .env")

    headers = {}
    if CLOUDFLARE_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {CLOUDFLARE_AUTH_TOKEN}"

    with httpx.Client(timeout=15) as client:
        response = client.get(f"{CLOUDFLARE_WORKER_URL}/pending", headers=headers)
        response.raise_for_status()
        return response.json()


def mark_transactions_synced(ids: list[str]) -> dict:
    if not ids:
        return {"status": "synced", "count": 0}

    if not CLOUDFLARE_WORKER_URL:
        raise ValueError("CLOUDFLARE_WORKER_URL is not set in .env")

    headers = {"Content-Type": "application/json"}
    if CLOUDFLARE_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {CLOUDFLARE_AUTH_TOKEN}"

    with httpx.Client(timeout=15) as client:
        response = client.post(
            f"{CLOUDFLARE_WORKER_URL}/sync",
            json={"ids": ids},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

