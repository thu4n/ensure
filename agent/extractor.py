from datetime import datetime
import json
import re
from mlx_lm import generate, load

from agent.config import EXTRACTION_SCHEMA, MODEL_ID


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
