#!/usr/bin/env bash
# Copy Secret Manager values into /run/gtm/env (root-only) before each worker start.
set -euo pipefail
umask 077
G=${GCLOUD:-gcloud}
OUT=${GTM_ENV_OUT:-/run/gtm/env}
TOKEN_DIR=${GTM_TOKEN_DIR:-/opt/gtm/.secrets}
LIST="$(dirname "$0")/secrets.txt"
d=$(dirname "$OUT"); mkdir -p "$d"
tmp=$(mktemp "$d/.env.XXXXXX"); err=$(mktemp "$d/.err.XXXXXX"); trap 'rm -f "$tmp" "$err"' EXIT
# Prints the value. Returns 1 on NOT_FOUND, 2 on any other gcloud failure (name and gcloud's error on stderr, never the value).
fetch() {
  "$G" secrets versions access latest --secret="$1" 2>"$err" && return 0 || true
  grep -q NOT_FOUND "$err" && return 1
  echo "fetch_secrets: $1: gcloud failed: $(cat "$err")" >&2; return 2
}
while read -r line; do
  name=${line%%#*}; name=${name//[[:space:]]/}
  [ -n "$name" ] || continue
  optional=; [[ $name == *\? ]] && { optional=1; name=${name%\?}; }
  rc=0; v=$(fetch "$name") || rc=$?
  [ "$rc" != 2 ] || exit 1
  if [ "$rc" = 0 ]; then
    v=${v//\\/\\\\}; v=${v//\"/\\\"}
    printf '%s="%s"\n' "$name" "$v" >> "$tmp"
  elif [ -z "$optional" ]; then
    echo "fetch_secrets: required secret $name is missing (NOT_FOUND)" >&2; exit 1
  fi
done < "$LIST"
mv "$tmp" "$OUT"
# Gmail OAuth token for the mailbox (optional; mailbox name from GTM_MAILBOX).
rc=0; t=$(fetch gmail-token) || rc=$?
[ "$rc" != 2 ] || exit 1
if [ "$rc" = 0 ]; then
  mkdir -p "$TOKEN_DIR"
  printf '%s' "$t" > "$TOKEN_DIR/token_${GTM_MAILBOX:-primary}.json"
  if [ "$(id -u)" = 0 ] && id gtm >/dev/null 2>&1; then chown -R gtm "$TOKEN_DIR"; fi
fi
