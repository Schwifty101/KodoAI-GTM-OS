#!/usr/bin/env bash
# Copy Secret Manager values into /run/gtm/env (root-only) before each worker start.
set -euo pipefail
umask 077
G=${GCLOUD:-gcloud}
OUT=${GTM_ENV_OUT:-/run/gtm/env}
TOKEN_DIR=${GTM_TOKEN_DIR:-/opt/gtm/.secrets}
LIST="$(dirname "$0")/secrets.txt"
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
while read -r line; do
  name=${line%%#*}; name=${name//[[:space:]]/}
  [ -n "$name" ] || continue
  optional=; [[ $name == *\? ]] && { optional=1; name=${name%\?}; }
  if v=$("$G" secrets versions access latest --secret="$name" 2>/dev/null); then
    v=${v//\\/\\\\}; v=${v//\"/\\\"}
    printf '%s="%s"\n' "$name" "$v" >> "$tmp"
  elif [ -z "$optional" ]; then
    echo "fetch_secrets: required secret $name is missing" >&2; exit 1
  fi
done < "$LIST"
mkdir -p "$(dirname "$OUT")"
mv "$tmp" "$OUT"; trap - EXIT
# Gmail OAuth token for the mailbox (optional; mailbox name from GTM_MAILBOX).
if t=$("$G" secrets versions access latest --secret=gmail-token 2>/dev/null); then
  mkdir -p "$TOKEN_DIR"
  printf '%s' "$t" > "$TOKEN_DIR/token_${GTM_MAILBOX:-primary}.json"
  if [ "$(id -u)" = 0 ] && id gtm >/dev/null 2>&1; then chown -R gtm "$TOKEN_DIR"; fi
fi
