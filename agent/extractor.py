from datetime import datetime
import json
import re
from mlx_lm import generate, load

from agent.config import BASE_DIR, EXTRACTION_SCHEMA, MODEL_ID

NOTIFICATION_EXTRACTION_SCHEMA = {
    "account": "string (must match one of the available accounts exactly)",
    "amount": "number (positive numeric transaction value, from the PS line)",
    "name": "string (concise title/merchant, primarily from ND line)",
    "description": "string (detailed info combining ND and SO GD metadata lines)",
    "currency": "string (e.g. VND, USD)",
    "date": "string (YYYY-MM-DD format extracted from the first line or today's date)",
    "category": "string (must match one of the available categories exactly)",
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


def extract_transaction_details(
    user_input: str,
    category_map: dict,
    account_map: dict,
    category_samples: dict = None,
    timestamp: str | datetime = None,
    model=None,
    tokenizer=None,
) -> dict:
    if model is None or tokenizer is None:
        model, tokenizer = load(MODEL_ID)
    today, current_time = _parse_timestamp(timestamp)

    available_categories = format_available_categories(category_map, category_samples)
    available_accounts = format_available_accounts(account_map)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a finance parsing assistant. Extract transaction details from user input into a single raw JSON object matching this schema:\n"
                f"{json.dumps(EXTRACTION_SCHEMA, indent=2)}\n\n"
                f"Today is {today}, and current time is {current_time}.\n"
                "If the user doesn't state a date or time in the input, use today's date and the current time.\n\n"
                f"Available categories:\n{available_categories}\n\n"
                f"Available accounts:\n{available_accounts}\n\n"
                "Instruction for category:\n"
                "- Choose the single best fitting category from the Available categories list for the 'category' field.\n"
                "- Use the provided example past transactions to understand each category's context and meaning.\n"
                "- Use the transaction timestamp / time of day to better categorize meals and spending:\n"
                "  * Morning (~06:00 - 10:30): Food/meals are typically breakfast ('Main Meals' or 'Food - Drinks'); morning coffee/tea is 'Drinks'.\n"
                "  * Midday / Lunch (~11:00 - 13:30): Food/meal purchases (e.g. rice, noodles, banh mi, lunch sets) are most likely lunch ('Main Meals', 'Food - Drinks', or 'Restaurant').\n"
                "  * Afternoon (~14:00 - 17:00): Beverages are typically coffee/tea ('Drinks') and snacks are 'Fruit & Snacks'.\n"
                "  * Evening / Dinner (~17:30 - 21:30): Food/dining purchases are typically dinner ('Main Meals', 'Restaurant', or 'Food - Drinks').\n"
                "  * Late night (~21:30 - 04:00): Late food, drinks, entertainment, or rides.\n"
                "- The 'category' field in your JSON output must be ONLY the category name exactly (do not include the example in the category value).\n\n"
                "Instruction for accounts:\n"
                "- Choose from the Available accounts list using the institution, account type, and subtype for context. If the input mentions 'THE TIN DUNG' or credit card, choose the corresponding account with Type: credit_card. If none specified, default to Wallet.\n"
                "- The 'account' field in your JSON output must be ONLY the exact account name (do not include the details in parentheses).\n\n"
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
    if "nature" not in parsed:
        parsed["nature"] = "expense"

    low_input = user_input.lower()
    if "the tin dung" in low_input or "credit" in low_input:
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
    category_map: dict,
    account_map: dict,
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

    available_categories = format_available_categories(category_map, category_samples)
    available_accounts = format_available_accounts(account_map)

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert banking notification parser. Extract transaction details from raw banking notification SMS/messages into a single raw JSON object matching this schema:\n"
                f"{json.dumps(NOTIFICATION_EXTRACTION_SCHEMA, indent=2)}\n\n"
                f"Today is {today}, and reference time is {current_time}.\n\n"
                f"Available accounts:\n{available_accounts}\n\n"
                f"Available categories:\n{available_categories}\n\n"
                "Here is a sample notification structure for reference (from sample_data.txt):\n"
                "```\n"
                f"{sample_notification}\n"
                "```\n\n"
                "How to parse each part of this notification:\n"
                "1. First Line (Account & Date/Time):\n"
                "   - The prefix (e.g. '(BankName)') or first line shows what bank/institution this is. ALWAYS match the account to the SAME institution in 'Available accounts'.\n"
                "   - Credit Card Hint: If the notification mentions 'THE TIN DUNG' (Vietnamese for Credit Card) or 'THE', match it to the credit card account (Type: credit_card) belonging to THAT same institution, NOT an ATM checking account and NOT another bank's card.\n"
                "   - The 'account' field in your JSON output must be ONLY the exact account name (do not include the details in parentheses).\n"
                "   - The date/time (e.g. '22/09/26;19:55' -> date '2026-09-22', time '19:55') gives the transaction timestamp. Convert the date to 'YYYY-MM-DD'. If unparseable, use today's date ({today}).\n"
                "2. Third Line / 'PS:' Line (Actual Amount & Nature):\n"
                "   - The 'PS' (Phat Sinh) line shows the actual transaction amount and whether it is income or expense.\n"
                "   - If 'PS:+' (has plus sign '+'): money was added/received into the account -> 'nature' MUST be 'income'.\n"
                "   - If 'PS:-' (has minus sign '-'): money was deducted/spent from the account -> 'nature' MUST be 'expense'.\n"
                "   - Parse 'amount' as a positive number (e.g. 2000, 5000). Vietnamese notation uses '.' as thousand separators.\n"
                "3. 'SD' Lines (Current Running Balance - IGNORE FOR AMOUNT):\n"
                "   - 'SD' (So Du) and 'SD KHA DUNG' lines are the current account balance (e.g. 'SD: 800.778VND').\n"
                "   - IGNORE these lines for now! They represent running balance, NOT the transaction amount. Do NOT use this value as the transaction amount. (Note: This will be used in the future to prevent balance mismatch).\n"
                "4. 'ND' & 'SO GD' Lines (Metadata for Name and Description):\n"
                "   - 'ND' (Noi Dung / content) and 'SO GD' (So Giao Dich / transaction ref) are metadata and very good info to have in the name of the transaction and the description.\n"
                "   - Use the 'ND' content as the transaction 'name' (e.g. 'ai do chuyen tien').\n"
                "   - Combine 'ND' and 'SO GD' into the 'description' (e.g. 'ai do chuyen tien | SO GD: 123x').\n"
                "5. Category Selection:\n"
                "   - Pick the single best fitting category from 'Available categories' using the ND text, sample past transactions, AND the notification timestamp / time of day for context:\n"
                "     * Morning (~06:00 - 10:30): Food transactions are typically breakfast ('Main Meals' or 'Food - Drinks'); morning coffee/tea is 'Drinks'.\n"
                "     * Midday / Lunch (~11:00 - 13:30): Food/dining transactions during this window are most likely lunch ('Main Meals', 'Food - Drinks', or 'Restaurant').\n"
                "     * Afternoon (~14:00 - 17:00): Beverages are typically coffee/tea ('Drinks') and snacks are 'Fruit & Snacks'.\n"
                "     * Evening / Dinner (~17:30 - 21:30): Dining/food transactions are typically dinner ('Main Meals', 'Restaurant', or 'Food - Drinks').\n"
                "     * Late night (~21:30 - 04:00): Late food, drinks, entertainment, or ride-hailing.\n\n"
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

    return parsed



