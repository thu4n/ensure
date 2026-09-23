import json
import sys
from mlx_lm import load

from agent.api import load_data, post_transaction
from agent.config import MODEL_ID
from agent.extractor import extract_transaction_details
from agent.resolver import build_payload


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
        print('Usage: ensure [--update] "<expense sentence>"')
        sys.exit(1)

    category_map, account_map, category_samples = load_data(force_update=update_flag)

    raw_input = " ".join(filtered_args).strip()
    if not raw_input:
        if update_flag:
            print("Cache updated successfully.")
            return
        else:
            print('Usage: ensure [--update] "<expense 1; expense 2; ...>"')
            sys.exit(1)

    transactions = [item.strip() for item in raw_input.split(";") if item.strip()]
    if not transactions:
        if update_flag:
            print("Cache updated successfully.")
            return
        else:
            print('Usage: ensure [--update] "<expense 1; expense 2; ...>"')
            sys.exit(1)

    total = len(transactions)
    if total > 1:
        print(f"Found {total} transactions to process.")

    model, tokenizer = load(MODEL_ID)
    success_count = 0

    for idx, tx_input in enumerate(transactions, start=1):
        prefix = f"[{idx}/{total}] " if total > 1 else ""
        print(f'\n{prefix}Parsing: "{tx_input}"...')

        try:
            parsed = extract_transaction_details(
                tx_input,
                category_map,
                account_map,
                category_samples,
                model=model,
                tokenizer=tokenizer,
            )
            print(f"Parsed by LLM:\n{json.dumps(parsed, indent=2)}")
            payload = build_payload(parsed, category_map, account_map)

            print("\nGenerated API Payload:")
            print(json.dumps(payload, indent=2))

            res = post_transaction(payload)
            print(f"\nResponse: {res}")
            success_count += 1
        except Exception as e:
            print(f'Error processing "{tx_input}": {e}', file=sys.stderr)

    if total > 1:
        print(f"\nCompleted: {success_count}/{total} transactions processed successfully.")
        if success_count < total:
            sys.exit(1)


if __name__ == "__main__":
    main()
