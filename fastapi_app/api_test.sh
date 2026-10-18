#!/bin/bash
# ARDesign API — curl command reference
# Usage: read and copy individual commands, or run this file end-to-end.
#
# Prerequisites: containers running via `docker compose up -d`

BASE="http://localhost:8000/api"

# ── 1. Register a new user ────────────────────────────────────────────────────
# Returns access_token and refresh_token.
echo "=== REGISTER ==="
curl -s -X POST "$BASE/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","email":"demo@example.com","password":"demopass123"}'
echo -e "\n"

# ── 2. Login ──────────────────────────────────────────────────────────────────
# Uses OAuth2 form encoding (username + password fields).
echo "=== LOGIN ==="
LOGIN=$(curl -s -X POST "$BASE/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=demo&password=demopass123")
echo "$LOGIN"

# Extract tokens (no python required)
TOKEN=$(echo "$LOGIN" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
REFRESH=$(echo "$LOGIN" | grep -o '"refresh_token":"[^"]*"' | cut -d'"' -f4)
echo -e "\n"

# ── 3. Get current user profile ───────────────────────────────────────────────
echo "=== ME ==="
curl -s "$BASE/auth/me" \
  -H "Authorization: Bearer $TOKEN"
echo -e "\n"

# ── 4. Refresh token ─────────────────────────────────────────────────────────
echo "=== REFRESH ==="
curl -s -X POST "$BASE/auth/refresh" \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\":\"$REFRESH\"}"
echo -e "\n"

# ── 5. Upload a patent ZIP ────────────────────────────────────────────────────
# Replace model.zip with your actual file path.
echo "=== UPLOAD ==="
# curl -s -X POST "$BASE/patents/upload" \
#   -H "Authorization: Bearer $TOKEN" \
#   -F "file=@model.zip"
echo "(uncomment and set file path to test)"
echo -e "\n"

# ── 6. Trigger conversion ────────────────────────────────────────────────────
# Replace 1 with the patent_id from the upload response.
echo "=== CONVERT ==="
# curl -s -X POST "$BASE/patents/1/convert" \
#   -H "Authorization: Bearer $TOKEN"
echo "(uncomment and set patent_id to test)"
echo -e "\n"

# ── 7. Poll conversion status ────────────────────────────────────────────────
echo "=== STATUS ==="
# curl -s "$BASE/patents/1/status" \
#   -H "Authorization: Bearer $TOKEN"
echo "(uncomment and set patent_id to test)"
echo -e "\n"

# ── 8. List all your patents ─────────────────────────────────────────────────
echo "=== LIST ==="
curl -s "$BASE/patents/" \
  -H "Authorization: Bearer $TOKEN"
echo -e "\n"

# ── 9. Download converted GLB ────────────────────────────────────────────────
echo "=== DOWNLOAD ==="
# curl -s -o model.glb "$BASE/patents/1/model" \
#   -H "Authorization: Bearer $TOKEN"
echo "(uncomment and set patent_id to test)"
echo -e "\n"

# ── 10. Delete a patent ──────────────────────────────────────────────────────
echo "=== DELETE ==="
# curl -s -X DELETE "$BASE/patents/1" \
#   -H "Authorization: Bearer $TOKEN" -w "\nHTTP %{http_code}\n"
echo "(uncomment and set patent_id to test)"