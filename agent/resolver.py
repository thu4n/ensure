from datetime import datetime

from agent.config import DEFAULT_ACCOUNT_ID, DEFAULT_CATEGORY_ID


def resolve_category_id(category_name: str, category_map: dict) -> str:
    fallback = DEFAULT_CATEGORY_ID or (next(iter(category_map.values()), "") if category_map else "")
    if not category_name:
        return fallback
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
    return fallback


def resolve_account_id(account_name: str, account_map: dict) -> str:
    fallback = DEFAULT_ACCOUNT_ID or ""
    if not fallback and account_map:
        first_val = next(iter(account_map.values()))
        fallback = first_val.get("id", "") if isinstance(first_val, dict) else (first_val or "")

    if not account_name:
        return fallback
    account_name = account_name.split("(")[0].strip()

    def _extract_id(val):
        if isinstance(val, dict):
            return val.get("id") or fallback
        return val or fallback

    if account_name in account_map:
        return _extract_id(account_map[account_name])
    lower_map = {k.lower(): v for k, v in account_map.items()}
    if account_name.lower() in lower_map:
        return _extract_id(lower_map[account_name.lower()])
    for k, v in account_map.items():
        if account_name.lower() in k.lower() or k.lower() in account_name.lower():
            return _extract_id(v)
    return fallback


def build_payload(parsed: dict, category_map: dict, account_map: dict) -> dict:
    category_id = resolve_category_id(parsed.get("category", ""), category_map)
    account_id = resolve_account_id(parsed.get("account", ""), account_map)
    nature = parsed.get("nature", "expense")
    if nature not in ("income", "expense"):
        nature = "expense"

    return {
        "transaction": {
            "account_id": account_id,
            "date": parsed.get("date", datetime.now().strftime("%Y-%m-%d")),
            "amount": parsed.get("amount", 0),
            "name": parsed.get("name", "Unknown Transaction"),
            "description": parsed.get("description", parsed.get("name", "")),
            "notes": parsed.get("notes", ""),
            "currency": parsed.get("currency", "VND"),
            "category_id": category_id,
            "nature": nature,
            "merchant_id": None,
            "tag_ids": [],
            "user_modified": True,
        }
    }

