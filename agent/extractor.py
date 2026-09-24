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


def extract_transaction_details(
    user_input: str,
    category_map: dict,
    account_map: dict,
    category_samples: dict = None,
    model=None,
    tokenizer=None,
) -> dict:
    if model is None or tokenizer is None:
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
    return parsed


def extract_notification_details(
    user_input: str,
    category_map: dict,
    account_map: dict,
    category_samples: dict = None,
    model=None,
    tokenizer=None,
) -> dict:
    if model is None or tokenizer is None:
        model, tokenizer = load(MODEL_ID)
    today = datetime.now().strftime("%Y-%m-%d")

    sample_file = BASE_DIR / "cloudflare" / "sample_data.txt"
    if sample_file.exists():
        sample_notification = sample_file.read_text(encoding="utf-8").strip()
    else:
        sample_notification = (
            "(TPBank): 22/09/26;19:55\n"
            "TK: xxxx9744901\n"
            "PS:+2.000VND\n"
            "SD: 800.778VND\n"
            "SD KHA DUNG: 800.778VND\n"
            "ND: ai do chuyen tien\n"
            "SO GD: 123x"
        )

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
                "You are an expert banking notification parser. Extract transaction details from raw banking notification SMS/messages into a single raw JSON object matching this schema:\n"
                f"{json.dumps(NOTIFICATION_EXTRACTION_SCHEMA, indent=2)}\n\n"
                f"Today is {today}.\n\n"
                f"Available accounts:\n[{available_accounts}]\n\n"
                f"Available categories:\n{available_categories}\n\n"
                "Here is a sample notification structure for reference (from sample_data.txt):\n"
                "```\n"
                f"{sample_notification}\n"
                "```\n\n"
                "How to parse each part of this notification:\n"
                "1. First Line (Account & Date/Time):\n"
                "   - The prefix (e.g. '(TPBank)') or first line shows what bank/account this is. Map it to the closest matching account in 'Available accounts' (e.g. 'TP Bank ATM').\n"
                "   - The date/time (e.g. '22/09/26' -> '2026-09-22') is the transaction date. Convert to 'YYYY-MM-DD'. If unparseable, use today's date.\n"
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
                "   - Pick the single best fitting category from 'Available categories' using the ND text and sample past transactions for context.\n\n"
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

    return parsed


