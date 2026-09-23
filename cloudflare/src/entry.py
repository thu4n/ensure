import hashlib
import json
from urllib.parse import parse_qs, urlparse
from workers import Response, WorkerEntrypoint


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        parsed_url = urlparse(request.url)
        path = parsed_url.path.rstrip("/") or "/"
        method = request.method

        # 1. Enforce authentication if AUTH_TOKEN is set in environment
        expected_token = getattr(self.env, "AUTH_TOKEN", None)
        if expected_token:
            auth_header = request.headers.get("Authorization") or ""
            token = None
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
            else:
                # Fallback: check query parameter ?token=... or ?key=...
                query = parse_qs(parsed_url.query)
                token = query.get("token", [None])[0] or query.get("key", [None])[0]

            if token != expected_token:
                return Response.json({"error": "Unauthorized"}, status=401)

        try:
            # Auto-initialize table if it doesn't exist
            await self.env.DB.prepare(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    raw TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    synced INTEGER DEFAULT 0,
                    synced_at DATETIME
                )
                """
            ).run()

            # 2. Ingest raw SMS: POST / or POST /ingest
            if method == "POST" and path in ("/", "/ingest"):
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

            # 3. Pull pending (unsynced) transactions: GET /pending
            if method == "GET" and path == "/pending":
                stmt = self.env.DB.prepare(
                    "SELECT id, raw, created_at FROM transactions WHERE synced = 0 ORDER BY created_at ASC"
                )
                result = await stmt.all()
                return Response.json(result.results, status=200)

            # 4. Acknowledge sync: POST /sync
            if method == "POST" and path == "/sync":
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