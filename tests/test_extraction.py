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
from agent.extractor import extract_notification_details, extract_transaction_details
from agent.resolver import build_payload

DATA_DIR = Path(__file__).resolve().parent / "data"


def test_item(raw_text: str, label: str, category_map: dict, account_map: dict, category_samples: dict, model, tokenizer):
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
            model=model,
            tokenizer=tokenizer,
        )
    else:
        parsed = extract_transaction_details(
            raw_text,
            category_map,
            account_map,
            category_samples,
            model=model,
            tokenizer=tokenizer,
        )

    print("\n--- Model Extracted JSON ---")
    print(json.dumps(parsed, indent=2, ensure_ascii=False))

    payload = build_payload(parsed, category_map, account_map)

    print("\n--- Resolved API Payload (Dry Run) ---")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


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

    # 1. Load cached categories and accounts (offline)
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
