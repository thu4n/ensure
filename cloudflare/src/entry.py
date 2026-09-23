import hashlib
import json
from workers import Response, WorkerEntrypoint


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = request.url
        method = request.method

        try:
            # 1. Phone pushes raw SMS text: POST /
            if method == "POST" and (url.endswith("/") or url.endswith("/ingest")):
                raw_text = (await request.text()).strip()
                if not raw_text:
                    return Response.json({"error": "Empty body"}, status=400)

                # Deterministic ID from raw SMS content (auto-deduplicates retries)
                msg_id = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]

                stmt = self.env.DB.prepare(
                    "INSERT OR IGNORE INTO transactions (id, raw) VALUES (?, ?)"
                ).bind(msg_id, raw_text)
                await stmt.run()

                return Response.json({"status": "received", "id": msg_id}, status=200)

            # 2. Local Mac pulls pending (unsynced) items: GET /pending
            if method == "GET" and url.endswith("/pending"):
                stmt = self.env.DB.prepare(
                    "SELECT id, raw, created_at FROM transactions WHERE synced = 0 ORDER BY created_at ASC"
                )
                result = await stmt.all()
                return Response.json(result.results, status=200)

            # 3. Local Mac marks items as synced after LLM & Sure API succeed: POST /sync
            if method == "POST" and url.endswith("/sync"):
                body = await request.json()
                ids = body.get("ids", [])
                if not ids and "id" in body:
                    ids = [body["id"]]

                if not ids:
                    return Response.json({"error": "No IDs provided"}, status=400)

                for msg_id in ids:
                    stmt = self.env.DB.prepare(
                        "UPDATE transactions SET synced = 1, synced_at = CURRENT_TIMESTAMP WHERE id = ?"
                    ).bind(msg_id)
                    await stmt.run()

                # Housekeeping: Safely purge synced items older than 14 days (never touches unsynced items)
                cleanup_stmt = self.env.DB.prepare(
                    "DELETE FROM transactions WHERE synced = 1 AND created_at < datetime('now', '-14 days')"
                )
                await cleanup_stmt.run()

                return Response.json({"status": "synced", "count": len(ids)}, status=200)

            return Response.json({"error": "Not Found"}, status=404)

        except Exception as e:
            return Response.json({"error": str(e)}, status=500)