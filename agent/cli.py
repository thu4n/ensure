import json
import sys
from mlx_lm import load

from agent.api import (
    cache_history,
    fetch_pending_transactions,
    load_data,
    mark_transactions_synced,
    post_transaction,
)
from agent.config import CLOUDFLARE_WORKER_URL, MODEL_ID
from agent.extractor import (
    extract_notification_details,
    extract_transaction_details,
)
from agent.resolver import build_payload


def print_usage():
    print('Usage: ensure [options] ["<expense sentence>"]')
    print("\nOptions:")
    print("  --sync-transactions, -s  Fetch and process pending transactions from Cloudflare Worker")
    print("  --cache-history          Cache transaction history to enrich model judgment")
    print("  --help, -h               Show this help message")
    print("\nExamples:")
    print('  ensure "45k banh mi for lunch"')
    print('  ensure "45k banh mi ; 30k coffee"')
    print("  ensure --sync-transactions")
    print("  ensure --cache-history")


def main():
    raw_args = sys.argv[1:]
    sync_flag = False
    cache_history_flag = False
    filtered_args = []

    for arg in raw_args:
        if arg in ("--sync-transactions", "-s"):
            sync_flag = True
        elif arg == "--cache-history":
            cache_history_flag = True
        elif arg in ("--help", "-h"):
            print_usage()
            sys.exit(0)
        else:
            filtered_args.append(arg)

    if not sync_flag and not cache_history_flag and not filtered_args:
        print_usage()
        sys.exit(1)

    if cache_history_flag:
        cache_history()
        if not sync_flag and not filtered_args:
            return

    category_map, account_map, category_samples = load_data()

    items_to_process: list[tuple[str, str | None]] = []

    if sync_flag:
        print(f"Connecting to Cloudflare Worker ({CLOUDFLARE_WORKER_URL or 'not configured'})...")
        try:
            pending = fetch_pending_transactions()
            print(f"Retrieved {len(pending)} pending item(s) from remote buffer.")
            for item in pending:
                raw_text = (item.get("raw") or "").strip()
                if raw_text:
                    items_to_process.append((raw_text, item.get("id")))
        except Exception as e:
            print(f"Error fetching from Cloudflare Worker: {e}", file=sys.stderr)
            sys.exit(1)

    raw_input = " ".join(filtered_args).strip()
    if raw_input:
        for item in raw_input.split(";"):
            tx = item.strip()
            if tx:
                items_to_process.append((tx, None))

    if not items_to_process:
        if sync_flag:
            print("No pending transactions to process.")
            return
        print_usage()
        sys.exit(1)

    total = len(items_to_process)
    print(f"\nProcessing {total} transaction(s). Loading local LLM ({MODEL_ID})...")
    model, tokenizer = load(MODEL_ID)
    success_count = 0

    for idx, (raw_text, cf_id) in enumerate(items_to_process, start=1):
        prefix = f"[{idx}/{total}] " if total > 1 else ""
        print(f'\n{prefix}Parsing: "{raw_text}"...')

        try:
            if cf_id or "\n" in raw_text or "PS:" in raw_text:
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
            print(f"Parsed by LLM:\n{json.dumps(parsed, indent=2)}")
            payload = build_payload(parsed, category_map, account_map)

            print("\nGenerated API Payload:")
            print(json.dumps(payload, indent=2))

            res = post_transaction(payload)
            print(f"\nResponse: {res}")

            if cf_id:
                mark_transactions_synced([cf_id])
                print(f"Acknowledged sync in Cloudflare D1 for ID: {cf_id}")

            success_count += 1
        except Exception as e:
            print(f'Error processing "{raw_text}": {e}', file=sys.stderr)

    if total > 1 or sync_flag:
        print(f"\nCompleted: {success_count}/{total} transactions processed successfully.")
        if success_count < total:
            sys.exit(1)


if __name__ == "__main__":
    main()
