from datetime import datetime
import json
import re
from mlx_lm import generate, load

from agent.config import BASE_DIR, CATEGORIZATION_SCHEMA, EXTRACTION_SCHEMA, MODEL_ID

NOTIFICATION_EXTRACTION_SCHEMA = {
    "account": "string (must match one of the available accounts exactly)",
    "amount": "number (positive numeric transaction value, from the PS line)",
    "name": "string (exact transaction content from the ND line)",
    "description": "string (detailed info combining ND and SO GD metadata lines)",
    "currency": "string (e.g. VND, USD)",
    "date": "string (YYYY-MM-DD format extracted from the first line or today's date)",
    "nature": "string ('income' if money added/PS:+, 'expense' if money spent/PS:-)",
}


def format_available_accounts(account_map: dict) -> str:
    account_lines = []
    for name, info in account_map.items():
        details = []
        if isinstance(info, dict):
            if info.get("institution_name"):
                details.append(f"Institution: {info['institution_name']}")
            if info.get("account_type"):
                details.append(f"Type: {info['account_type']}")
            sub = info.get("subtype") or info.get("sub_type")
            if sub:
                details.append(f"Subtype: {sub}")
            if info.get("balance"):
                details.append(f"Balance: ~{info['balance']}")

        if details:
            account_lines.append(f'- "{name}" ({", ".join(details)})')
        else:
            account_lines.append(f'- "{name}"')
    return "\n".join(account_lines)


def format_available_categories(category_map: dict, category_samples: dict = None) -> str:
    category_samples = category_samples or {}
    category_lines = []
    for name in category_map.keys():
        sample_val = category_samples.get(name)
        names = []
        if isinstance(sample_val, list):
            names = [str(x).strip() for x in sample_val if str(x).strip()]
        elif isinstance(sample_val, dict):
            if sample_val.get("name"):
                names = [sample_val["name"].strip()]
        elif isinstance(sample_val, str) and sample_val.strip():
            names = [sample_val.strip()]

        if names:
            cleaned = []
            for n in names[:3]:
                c = " ".join(n.split())
                if len(c) > 40:
                    c = c[:37] + "..."
                cleaned.append(f'"{c}"')
            if len(cleaned) == 1:
                category_lines.append(f'- "{name}" (example: {cleaned[0]})')
            else:
                category_lines.append(f'- "{name}" (examples: {", ".join(cleaned)})')
        else:
            category_lines.append(f'- "{name}"')

    return "\n".join(category_lines)


def _parse_timestamp(timestamp: str | datetime | None = None) -> tuple[str, str]:
    if timestamp is None:
        now = datetime.now()
        return now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    if isinstance(timestamp, datetime):
        return timestamp.strftime("%Y-%m-%d"), timestamp.strftime("%H:%M")
    ts_str = str(timestamp).strip().replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(ts_str.split(".")[0], fmt)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
        except ValueError:
            continue
    now = datetime.now()
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M")


def _correct_truncated_amount(amount: int | float | None, raw_text: str) -> int | float | None:
    if amount is not None and amount < 1000:
        # Check if the text has something like 64.120 or 64,120 where 64 was extracted
        match = re.search(rf"\b({int(amount)})[\.,](\d{{3}})\b", raw_text)
        if match:
            return int(match.group(1) + match.group(2))
    return int(amount) if amount is not None else amount


def extract_transaction_details(
    user_input: str,
    category_map: dict = None,
    account_map: dict = None,
    category_samples: dict = None,
    timestamp: str | datetime = None,
    model=None,
    tokenizer=None,
) -> dict:
    if model is None or tokenizer is None:
        model, tokenizer = load(MODEL_ID)
    today, current_time = _parse_timestamp(timestamp)

    available_accounts = format_available_accounts(account_map or {})

    messages = [
        {
            "role": "system",
            "content": (
                "You are a finance parsing assistant. Extract transaction details from user input into a single raw JSON object matching this schema:\n"
                f"{json.dumps(EXTRACTION_SCHEMA, indent=2)}\n\n"
                f"Today is {today}, and current time is {current_time}.\n"
                "If the user doesn't state a date or time in the input, use today's date.\n\n"
                f"Available accounts:\n{available_accounts}\n\n"
                "Instruction for accounts:\n"
                "- Choose from the Available accounts list using the institution, account type, and subtype for context.\n"
                "- If the input mentions 'THE TIN DUNG' or credit card, choose the corresponding account with Type: credit_card.\n"
                "- For bank transactions/transfers (e.g. TP Bank), use the primary checking / ATM account (Subtype: checking, e.g. 'Main ATM'). Do NOT choose savings or emergency funds (e.g. 'Emergency Fund') unless explicitly specified.\n"
                "- If none specified, default to Wallet.\n"
                "- The 'account' field in your JSON output must be ONLY the exact account name (do not include the details in parentheses).\n\n"
                "Instruction for amount:\n"
                "- Parse 'amount' as positive numeric value: convert 45k -> 45000, and treat dots/commas as thousand separators in VND (e.g. '64.120' or '64,120' -> 64120, not 64).\n\n"
                "Instruction for nature:\n"
                "- Choose 'income' if the input indicates receiving money, salary, bonus, refund, cashback, etc.\n"
                "- Choose 'expense' for purchases, spending, bills, or fees.\n\n"
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

    parsed = json.loads(match.group(0))
    parsed["amount"] = _correct_truncated_amount(parsed.get("amount"), user_input)
    if "nature" not in parsed:
        parsed["nature"] = "expense"
    parsed["time"] = current_time

    low_input = user_input.lower()
    if account_map and ("the tin dung" in low_input or "credit" in low_input):
        current_acc = parsed.get("account", "")
        acc_info = account_map.get(current_acc, {})
        if not (isinstance(acc_info, dict) and acc_info.get("account_type") == "credit_card"):
            for name, info in account_map.items():
                if isinstance(info, dict) and info.get("account_type") == "credit_card":
                    inst = str(info.get("institution_name") or "").lower().strip()
                    inst_nospace = inst.replace(" ", "")
                    acc_name_low = name.lower().strip()
                    if (inst and inst in low_input) or (inst_nospace and inst_nospace in low_input) or (acc_name_low and acc_name_low in low_input):
                        parsed["account"] = name
                        break

    return parsed


def extract_notification_details(
    user_input: str,
    category_map: dict = None,
    account_map: dict = None,
    category_samples: dict = None,
    timestamp: str | datetime = None,
    model=None,
    tokenizer=None,
) -> dict:
    if model is None or tokenizer is None:
        model, tokenizer = load(MODEL_ID)
    today, current_time = _parse_timestamp(timestamp)

    sample_file = BASE_DIR / "cloudflare" / "sample_data.txt"
    if sample_file.exists():
        sample_notification = sample_file.read_text(encoding="utf-8").strip()
    else:
        sample_notification = (
            "(BankName): 22/09/26;19:55\n"
            "TK: xxxx0000000\n"
            "PS:+2.000VND\n"
            "SD: 800.000VND\n"
            "SD KHA DUNG: 800.000VND\n"
            "ND: ai do chuyen tien\n"
            "SO GD: 123x"
        )

    available_accounts = format_available_accounts(account_map or {})

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert banking notification parser. Extract transaction details from raw banking notification SMS/messages into a single raw JSON object matching this schema:\n"
                f"{json.dumps(NOTIFICATION_EXTRACTION_SCHEMA, indent=2)}\n\n"
                f"Today is {today}, and reference time is {current_time}.\n\n"
                f"Available accounts:\n{available_accounts}\n\n"
                "Here is a sample notification structure for reference (from sample_data.txt):\n"
                "```\n"
                f"{sample_notification}\n"
                "```\n\n"
                "How to parse each part of this notification:\n"
                "1. First Line (Account & Date/Time):\n"
                "   - The prefix (e.g. '(BankName)') or first line shows what bank/institution this is. ALWAYS match the account to the SAME institution in 'Available accounts'.\n"
                "   - Account type and Balance Hint:\n"
                "     * If the notification mentions 'THE TIN DUNG' (Vietnamese for Credit Card) or 'THE', match it to the credit card account (Type: credit_card) belonging to THAT same institution, NOT an ATM checking account and NOT another bank's card.\n"
                "     * For standard bank notifications (e.g. with 'TK: ...'), use the running balance ('SD:' or 'SD KHA DUNG:') to match the account with the closest Balance (e.g. checking/ATM account vs dedicated savings/emergency fund).\n"
                "   - The 'account' field in your JSON output must be ONLY the exact account name (do not include the details in parentheses).\n"
                "   - The date/time (e.g. '22/09/26;19:55' -> date '2026-09-22', time '19:55') gives the transaction timestamp. Convert the date to 'YYYY-MM-DD'. If unparseable, use today's date ({today}).\n"
                "2. Third Line / 'PS:' Line (Actual Amount & Nature):\n"
                "   - The 'PS' (Phat Sinh) line shows the actual transaction amount and whether it is income or expense.\n"
                "   - If 'PS:+' (has plus sign '+'): money was added/received into the account -> 'nature' MUST be 'income'.\n"
                "   - If 'PS:-' (has minus sign '-'): money was deducted/spent from the account -> 'nature' MUST be 'expense'.\n"
                "   - Parse 'amount' as a positive number (e.g. 2000, 64120). In Vietnamese notation, dots '.' and commas ',' are thousand separators (e.g. '64.120' is 64120, not 64; '2.000' is 2000, not 2).\n"
                "3. 'SD' Lines (Current Running Balance - USE FOR ACCOUNT MATCHING, NOT TRANSACTION AMOUNT):\n"
                "   - 'SD' (So Du) and 'SD KHA DUNG' lines are the current account balance (e.g. 'SD: 800.778VND').\n"
                "   - Do NOT use this value as the transaction amount! Use it to match which account the transaction belongs to by comparing against account balances.\n"
                "4. 'ND' & 'SO GD' Lines (Metadata for Name and Description):\n"
                "   - 'ND' (Noi Dung / content) and 'SO GD' (So Giao Dich / transaction ref) are metadata and very good info to have in the name of the transaction and the description.\n"
                "   - Preserve the full 'ND' content verbatim as the transaction 'name' (e.g. 'ai do chuyen tien') so downstream rules can match against it.\n"
                "   - Combine 'ND' and 'SO GD' into the 'description' (e.g. 'ai do chuyen tien | SO GD: 123x').\n\n"
                "Return ONLY valid raw JSON. No explanations, no markdown blocks."
            ),
        },
        {"role": "user", "content": user_input},
    ]

    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    raw_output = generate(model, tokenizer, prompt=prompt, max_tokens=300, verbose=False)

    match = re.search(r"\{.*\}", raw_output, re.DOTALL)
    if not match:
        raise ValueError(f"Failed to extract JSON from model output:\n{raw_output}")

    parsed = json.loads(match.group(0))

    # Deterministic ND extraction so Sure's rules match against exact bank ND strings
    nd_match = re.search(r"^ND:\s*(.+)$", user_input, re.MULTILINE | re.IGNORECASE)
    if nd_match:
        nd_val = nd_match.group(1).strip()
        if nd_val:
            parsed["name"] = nd_val

    # Extract transaction time HH:MM from SMS text if present
    time_match = re.search(r"(?:;|\s)([01]?\d|2[0-3]):([0-5]\d)\b", user_input)
    if time_match:
        parsed["time"] = f"{int(time_match.group(1)):02d}:{time_match.group(2)}"
    else:
        parsed["time"] = current_time

    # Deterministic amount extraction from PS line for banking SMS
    ps_match = re.search(r"PS:\s*[\+\-]?\s*([0-9\.,]+)", user_input, re.IGNORECASE)
    if ps_match:
        digits = re.sub(r"[^\d]", "", ps_match.group(1).strip())
        if digits:
            try:
                parsed["amount"] = int(digits)
            except ValueError:
                pass
    parsed["amount"] = _correct_truncated_amount(parsed.get("amount"), user_input)

    # Deterministic check for PS:+ (income) and PS:- (expense) from banking SMS
    if re.search(r"PS:\s*\+", user_input):
        parsed["nature"] = "income"
    elif re.search(r"PS:\s*-", user_input):
        parsed["nature"] = "expense"
    elif "nature" not in parsed:
        parsed["nature"] = "expense"

    # Deterministic check for "THE TIN DUNG" (Credit Card) matching the correct institution dynamically
    low_input = user_input.lower()
    is_credit = "the tin dung" in low_input or "credit" in low_input
    account_map = account_map or {}
    if is_credit:
        matched_card = None
        for name, info in account_map.items():
            if isinstance(info, dict) and info.get("account_type") == "credit_card":
                inst = str(info.get("institution_name") or "").lower().strip()
                inst_nospace = inst.replace(" ", "")
                acc_name_low = name.lower().strip()
                if (inst and inst in low_input) or (inst_nospace and inst_nospace in low_input) or (acc_name_low and acc_name_low in low_input):
                    matched_card = name
                    break
        if not matched_card:
            for name, info in account_map.items():
                if isinstance(info, dict) and info.get("account_type") == "credit_card":
                    matched_card = name
                    break
        if matched_card:
            parsed["account"] = matched_card
    else:
        # Balance-based disambiguation using running balance 'SD'
        sd_match = re.search(r"SD(?:\s+KHA\s+DUNG)?:\s*([0-9\.,]+)", user_input, re.IGNORECASE)
        if sd_match:
            digits = re.sub(r"[^\d]", "", sd_match.group(1).strip())
            if digits:
                sd_val = int(digits)
                parsed["running_balance"] = sd_val

                # Find matching institution from the notification text
                matched_inst = None
                for name, info in account_map.items():
                    if isinstance(info, dict) and info.get("institution_name"):
                        inst = info["institution_name"].lower()
                        inst_nospace = inst.replace(" ", "")
                        if inst in low_input or inst_nospace in low_input:
                            matched_inst = info["institution_name"]
                            break

                candidates = []
                for name, info in account_map.items():
                    if isinstance(info, dict):
                        if matched_inst and info.get("institution_name") != matched_inst:
                            continue
                        if info.get("account_type") == "credit_card":
                            continue
                        if info.get("balance_cents") is not None:
                            candidates.append((name, info["balance_cents"]))

                if candidates:
                    closest_name, _ = min(
                        candidates,
                        key=lambda c: abs(c[1] - sd_val)
                    )
                    parsed["account"] = closest_name

    return parsed


def categorize_transaction(
    tx: dict,
    category_map: dict,
    category_samples: dict = None,
    model=None,
    tokenizer=None,
) -> str:
    if model is None or tokenizer is None:
        model, tokenizer = load(MODEL_ID)

    available_categories = format_available_categories(category_map, category_samples)

    tx_name = tx.get("name") or ""
    tx_notes = tx.get("notes") or ""
    tx_amount = tx.get("amount") or tx.get("amount_cents") or ""
    tx_nature = tx.get("classification") or tx.get("nature") or "expense"
    tx_date = tx.get("date") or ""
    tx_account = (
        tx.get("account", {}).get("name")
        if isinstance(tx.get("account"), dict)
        else (tx.get("account") or "")
    )
    tx_merchant = (
        tx.get("merchant", {}).get("name")
        if isinstance(tx.get("merchant"), dict)
        else (tx.get("merchant") or "")
    )
    tx_tags = [
        t.get("name") if isinstance(t, dict) else str(t)
        for t in (tx.get("tags") or [])
    ]

    tx_summary_lines = [
        f"Name: {tx_name}",
        f"Amount: {tx_amount} ({tx_nature})",
        f"Date: {tx_date}",
    ]
    if tx_account:
        tx_summary_lines.append(f"Account: {tx_account}")
    if tx_notes:
        tx_summary_lines.append(f"Notes: {tx_notes}")
    if tx_merchant:
        tx_summary_lines.append(f"Merchant: {tx_merchant}")
    if tx_tags:
        tx_summary_lines.append(f"Tags: {', '.join(tx_tags)}")

    tx_summary = "\n".join(tx_summary_lines)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a finance categorization assistant. Decide the single best category for an uncategorized transaction and return a raw JSON object matching this schema:\n"
                f"{json.dumps(CATEGORIZATION_SCHEMA, indent=2)}\n\n"
                f"Available categories:\n{available_categories}\n\n"
                "Instructions:\n"
                "- Choose the single best fitting category from the Available categories list for the 'category' field.\n"
                "- Prefer specific subcategories ('Main Meals', 'Drinks', 'Restaurant', 'Fruit & Snacks') over broad parent categories ('Food - Drinks').\n"
                "- Use the provided example past transactions and any 'Time: HH:MM' in Notes to understand meal/beverage timing:\n"
                "  * Morning (~06:00 - 10:30): Food/meals are typically breakfast ('Main Meals'); morning coffee/tea is 'Drinks'.\n"
                "  * Midday / Lunch (~11:00 - 13:30): Food/meal purchases (including GrabFood lunch orders) are most likely lunch ('Main Meals' or 'Restaurant').\n"
                "  * Afternoon (~14:00 - 17:00): Beverages or lower-cost food/snack orders in the afternoon are typically coffee/tea ('Drinks') and snacks are 'Fruit & Snacks'.\n"
                "  * Evening / Dinner (~17:30 - 21:30): Food/dining purchases are typically dinner ('Main Meals' or 'Restaurant').\n"
                "  * Late night (~21:30 - 04:00): Late food, drinks, entertainment, or rides.\n"
                "- If the transaction is an 'income' (e.g. money received, transfer in, cashback, salary), pick an appropriate income/transfer/gift category.\n"
                "- The 'category' field in your JSON output must be ONLY the category name exactly (do not include the examples).\n\n"
                "Return ONLY valid raw JSON. No explanations, no markdown blocks."
            ),
        },
        {"role": "user", "content": tx_summary},
    ]

    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    raw_output = generate(model, tokenizer, prompt=prompt, max_tokens=100, verbose=False)

    match = re.search(r"\{.*\}", raw_output, re.DOTALL)
    if not match:
        raise ValueError(f"Failed to extract JSON from model output:\n{raw_output}")

    parsed = json.loads(match.group(0))
    return (parsed.get("category") or "").strip()




