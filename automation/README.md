# Task 2 — No-code automation (n8n)

**Flow:** `n8n_duplicate_alert_flow.json` — *New Person Duplicate Alert.*

When a new person arrives (webhook), the flow asks the merged database whether
we already know them and, if so, fires a Slack alert. It is wired to the exact
same normalization used in Task 1, so a phone typed as `098450 12345` still
matches the stored `9845012345`.

```
Webhook (POST /new-person)
        │
        ▼
HTTP Request ──► POST http://<app>/api/check_duplicate   (the Python API from Task 3)
        │        returns { is_duplicate, matched_on, person }
        ▼
   IF is_duplicate ?
    ├── true ──► Build Slack message ──► Send Slack Alert ──► Respond "duplicate"
    └── false ─────────────────────────────────────────────► Respond "new"
```

Why this shape: the *decision and orchestration* live in n8n (no code), while
the one thing that genuinely needs code — normalizing messy phone/email and
querying SQLite — is a tiny, testable Python endpoint. n8n calls it over HTTP.

## Run it

1. **Start the Python API** (it also serves the Task-3 app):
   ```bash
   python app/app.py          # exposes /api/check_duplicate on :5000
   ```

2. **Start n8n** (Docker is easiest, free, self-hosted):
   ```bash
   docker run -it --rm -p 5678:5678 \
     -e N8N_SECURE_COOKIE=false \
     docker.n8n.io/n8nio/n8n
   ```
   Open http://localhost:5678.

3. **Import the flow:** n8n → *Workflows* → *Import from File* →
   `automation/n8n_duplicate_alert_flow.json`.

4. *(optional)* Set a real Slack Incoming Webhook so the alert lands in a
   channel: add an env var `SLACK_WEBHOOK_URL=...` to the n8n container, or
   paste the URL into the **Send Slack Alert** node. Without it the flow still
   runs and returns the duplicate verdict in the webhook response.

5. **Activate** the workflow (top-right toggle) and copy the Webhook URL.

> Note on networking: from the n8n Docker container, the host's Flask app is
> reached at `http://host.docker.internal:5000` (already set in the HTTP node).
> On Linux, add `--add-host=host.docker.internal:host-gateway` to the
> `docker run` command.

## Test it

Known duplicate (Priya, messy phone) → expect a Slack alert + `"status":"duplicate"`:
```bash
curl -X POST http://localhost:5678/webhook/new-person \
  -H "Content-Type: application/json" \
  -d '{"name":"Priya Nair","phone":"098450 12345","email":"priyanair@gmail.com"}'
```

Brand-new person → expect `"status":"new"`:
```bash
curl -X POST http://localhost:5678/webhook/new-person \
  -H "Content-Type: application/json" \
  -d '{"name":"Brand New","phone":"9123456780","email":"new@example.com"}'
```

`send_test_events.sh` in this folder fires both for the video.
