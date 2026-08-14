#!/bin/sh
# Rung 1 of the fetch skill — one request, one verdict line on stdout. See SKILL.md.
#
#   curl-verdict.sh <url> <name> [curl options…]   # appended, so they win
set -eu

[ $# -ge 2 ] || {
	echo "usage: curl-verdict.sh <url> <name> [curl options…]" >&2
	exit 2
}
URL=$1
OUT=$2
shift 2

# The second argument is a *name*, not a path: whatever directory it carries is dropped. The cwd
# is whatever the session is rooted at and a downloaded page is scratch rather than content of it,
# so the directory is not the caller's to choose — a rule with an opt-out is one that gets opted
# out of, on the call where it mattered. `FETCH_DIR` moves every download at once, deliberately;
# the verdict line says where the file actually went.
FETCH_DIR=${FETCH_DIR:-/tmp/fetch/${CLAUDE_CODE_SESSION_ID:-shared}}
OUT="$FETCH_DIR/$(basename "$OUT")"
mkdir -p "$FETCH_DIR"

# macOS assumption — elsewhere pass your own --user-agent, or the string contradicts the stack.
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15'

# Homebrew's curl (keg-only, hence the full path), else PATH's — Apple's gets blocked more.
CURL=$(command -v /opt/homebrew/opt/curl/bin/curl || command -v curl)

# The --header values below cannot be replaced from the command line: an appended --header is
# added, never substituted, and curl's removal trick (--header 'Accept:') only drops headers
# curl generated itself. Edit here if a default has to change.
exec "$CURL" --silent --show-error --location --compressed --http2 --max-time 30 \
	--user-agent "$UA" \
	--header 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' \
	--header 'Accept-Language: fr-FR,fr;q=0.9,en;q=0.8' \
	--cookie-jar "$OUT.cookies" --cookie "$OUT.cookies" \
	--retry 2 --retry-connrefused \
	--output "$OUT" \
	--write-out 'http=%{http_code} %{size_download}b %{content_type} HTTP/%{http_version} redir=%{num_redirects} %{time_total}s file=%{filename_effective} %{url_effective}\n' \
	"$@" "$URL"
