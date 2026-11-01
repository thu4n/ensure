#!/usr/bin/env -S uv run python
import json
import sys
from pathlib import Path
from mlx_lm import load

# Ensure repository root is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from agent.api import load_data
from agent.config import MODEL_ID
from agent.extractor import (
    categorize_transaction,
    extract_notification_details,
    extract_transaction_details,
)
from agent.resolver import build_import_csv, build_import_row, resolve_category_id

DATA_DIR = Path(__file__).resolve().parent / "data"


def test_item(
    raw_text: str,
    label: str,
    category_map: dict,
    account_map: dict,
    category_samples: dict,
    model,
    tokenizer,
    timestamp: str = None,
):
    print(f"\n{'=' * 20} Testing: {label} {'=' * 20}")
    print("--- Raw Input ---")
    print(raw_text)
    print("-----------------")

    is_notification = "\n" in raw_text or "PS:" in raw_text or raw_text.startswith("(")
    if is_notification:
        parsed = extract_notification_details(
            raw_text,
            category_map,
            account_map,
            category_samples,
            timestamp=timestamp,
            model=model,
            tokenizer=tokenizer,
        )
    else:
        parsed = extract_transaction_details(
            raw_text,
            category_map,
            account_map,
            category_samples,
            timestamp=timestamp,
            model=model,
            tokenizer=tokenizer,
        )

    print("\n--- [Phase 1] Model Extracted JSON (No Category) ---")
    print(json.dumps(parsed, indent=2, ensure_ascii=False))

    import_row = build_import_row(parsed, account_map)
    csv_preview = build_import_csv([import_row])

    print("\n--- [Phase 1] Generated Import CSV (Dry Run) ---")
    print(csv_preview.strip())

    # Simulate Phase 2: if Sure rules didn't categorize it, test local LLM categorization
    simulated_tx = {
        "name": import_row["name"],
        "amount": abs(import_row["amount"]),
        "classification": parsed.get("nature", "expense"),
        "date": import_row["date"],
        "notes": import_row["notes"],
        "account": {"name": parsed.get("account", "")},
    }
    cat_name = categorize_transaction(
        simulated_tx,
        category_map=category_map,
        category_samples=category_samples,
        model=model,
        tokenizer=tokenizer,
    )
    cat_id = resolve_category_id(cat_name, category_map)

    print("\n--- [Phase 2] Fallback LLM Categorization (If Uncategorized After Import) ---")
    print(json.dumps({"category": cat_name, "category_id": cat_id}, indent=2, ensure_ascii=False))


def main():
    targets = []

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        target_path = Path(arg)
        if target_path.is_file():
            targets.append((target_path.read_text(encoding="utf-8").strip(), target_path.name))
        elif target_path.is_dir():
            for f in sorted(target_path.glob("*.txt")):
                targets.append((f.read_text(encoding="utf-8").strip(), f.name))
        else:
            raw = " ".join(sys.argv[1:]).strip()
            targets.append((raw, "CLI Input"))
    else:
        # Default: run on all test files in tests/data/
        test_files = sorted(DATA_DIR.glob("*.txt"))
        if not test_files:
            # Fallback to cloudflare/sample_data.txt
            fallback = BASE_DIR / "cloudflare" / "sample_data.txt"
            if fallback.exists():
                test_files = [fallback]

        for f in test_files:
            targets.append((f.read_text(encoding="utf-8").strip(), f.name))

    if not targets:
        print("No test data found in tests/data/ and no arguments provided.", file=sys.stderr)
        sys.exit(1)

    # 1. Load cached categories and accounts
    category_map, account_map, category_samples = load_data()

    # 2. Load model once
    print(f"Loading model: {MODEL_ID}...")
    model, tokenizer = load(MODEL_ID)

    # 3. Run tests
    for raw_text, label in targets:
        test_item(raw_text, label, category_map, account_map, category_samples, model, tokenizer)

    print(f"\n{'=' * 20} Completed {len(targets)} test(s) {'=' * 20}\n")


if __name__ == "__main__":
    main()
