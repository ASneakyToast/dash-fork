#!/bin/sh
# Mint a GitHub App installation token into $OUT_DIR/token.
# Tokens live 1h, so INTERVAL_SECONDS must stay well under 3600.
set -u

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

jwt() {
  now=$(date +%s)
  header=$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)
  payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' \
    $((now - 60)) $((now + 540)) "$(cat "$APP_DIR/GITHUB_APP_ID")" | b64url)
  signature=$(printf '%s.%s' "$header" "$payload" \
    | openssl dgst -sha256 -sign "$APP_DIR/GITHUB_APP_PRIVATE_KEY" | b64url)
  printf '%s.%s.%s' "$header" "$payload" "$signature"
}

mint() {
  curl -fsS -X POST \
    -H "Authorization: Bearer $(jwt)" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/app/installations/$(cat "$APP_DIR/GITHUB_APP_INSTALLATION_ID")/access_tokens" \
    | jq -er .token
}

mkdir -p "$OUT_DIR"
while true; do
  if token=$(mint); then
    printf '%s' "$token" > "$OUT_DIR/token.tmp"
    chmod 0444 "$OUT_DIR/token.tmp"
    mv "$OUT_DIR/token.tmp" "$OUT_DIR/token"
    echo "minted token"
  else
    echo "mint failed, keeping previous token" >&2
  fi
  sleep "$INTERVAL_SECONDS"
done
