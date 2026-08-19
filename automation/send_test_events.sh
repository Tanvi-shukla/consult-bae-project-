#!/usr/bin/env bash
# Fire two test events at the n8n webhook for the demo video.
# Usage: ./send_test_events.sh [webhook_base_url]
# Default assumes n8n test webhook at http://localhost:5678/webhook/new-person
set -euo pipefail
URL="${1:-http://localhost:5678/webhook/new-person}"

echo "== Known duplicate (Priya Nair, messy phone) =="
curl -sS -X POST "$URL" -H "Content-Type: application/json" \
  -d '{"name":"Priya Nair","phone":"098450 12345","email":"priyanair@gmail.com"}'
echo -e "\n"

echo "== Brand new person =="
curl -sS -X POST "$URL" -H "Content-Type: application/json" \
  -d '{"name":"Brand New","phone":"9123456780","email":"new@example.com"}'
echo
