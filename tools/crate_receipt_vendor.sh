#!/usr/bin/env bash
# Vendor, or check, crate's receipt contract at a pinned tag.
#
# The test suite is offline: conftest.py refuses every non-loopback lookup and connection for
# the whole session, so no test can fetch a vector or a schema. The contract therefore lives in
# the repository, and this script is the only thing that fetches it.
#
#   bash tools/crate_receipt_vendor.sh vendor   # download into the repo (writes)
#   bash tools/crate_receipt_vendor.sh check    # download to a temp dir and diff (read-only)
#
# `check` is what CI runs, BEFORE pytest, because it is the one step that needs the network. It
# answers two different questions:
#
#   1. Are the vendored bytes the ones crate published at CRATE_TAG? A diff against the tag
#      catches an edited vendored file, and a moved tag.
#   2. Does each frozen schema URL still serve those bytes? crate's rule is that a published
#      version is never edited; this is that rule enforced from the consumer's side.
#
# Fetched over plain HTTPS from a public repository, so it needs no credentials and works the
# same locally and in Actions. --fail turns an HTTP error into a non-zero exit, and -L follows
# the redirect that the schema URLs serve (without it curl saves the redirect page as the file).

set -euo pipefail

CRATE_TAG=v0.12.0
CRATE_REPO=NewGraphEnvironment/crate
RAW="https://raw.githubusercontent.com/${CRATE_REPO}/${CRATE_TAG}"

# Where each file comes from in crate, and where it lands here. Two destinations, for two
# different promises:
#
#   tests/vectors/receipt/v1.0.0/  the executable half of the contract. Frozen with the schema
#                                 version: "a change is a new version directory, never an edit".
#   src/stacs/data/receipt/       what the package itself reads at run time. The schemas are
#                                 frozen by their version URL; register.csv and mapping.csv are
#                                 NOT versioned in crate, so they are pinned to CRATE_TAG and
#                                 may gain rows in a later one.
#
# One space-separated "<source path> <destination path>" per line.
FILES='
inst/extdata/receipt/vectors/v1.0.0/numbers.json tests/vectors/receipt/v1.0.0/numbers.json
inst/extdata/receipt/vectors/v1.0.0/jcs.json tests/vectors/receipt/v1.0.0/jcs.json
inst/extdata/receipt/vectors/v1.0.0/recipe_id.json tests/vectors/receipt/v1.0.0/recipe_id.json
inst/extdata/receipt/vectors/v1.0.0/fingerprint.json tests/vectors/receipt/v1.0.0/fingerprint.json
inst/extdata/receipt/vectors/v1.0.0/compare.json tests/vectors/receipt/v1.0.0/compare.json
inst/extdata/receipt/vectors/v1.0.0/README.md tests/vectors/receipt/v1.0.0/README.md
pkgdown/assets/receipt/v1.0.0/schema.json src/stacs/data/receipt/v1.0.0/schema.json
pkgdown/assets/stac/receipt/v1.0.0/schema.json src/stacs/data/receipt/v1.0.0/stac_schema.json
inst/extdata/receipt/register.csv src/stacs/data/receipt/register.csv
inst/extdata/receipt/mapping.csv src/stacs/data/receipt/mapping.csv
inst/extdata/receipt/examples/worked_case/build_1/receipt.json tests/vectors/receipt/examples/worked_case/build_1/receipt.json
inst/extdata/receipt/examples/worked_case/build_2/receipt.json tests/vectors/receipt/examples/worked_case/build_2/receipt.json
pkgdown/assets/stac/receipt/examples/item.json tests/vectors/receipt/examples/item.json
'
# The worked case and the example item are not vectors -- no expected value is computed from
# them -- but they are the only fixtures that pin two things a vector cannot: the bytes a
# receipt FILE has on disk (canonical JSON, pretty-printed at indent 2, empty containers
# collapsed, one trailing newline), and a real item carrying the mirrored identity fields.

# The frozen URLs the package writes into receipts and items, each with the vendored copy that
# must still match it. These are the ones crate promises never to edit.
URLS='
https://newgraphenvironment.github.io/crate/receipt/v1.0.0/schema.json src/stacs/data/receipt/v1.0.0/schema.json
https://newgraphenvironment.github.io/crate/stac/receipt/v1.0.0/schema.json src/stacs/data/receipt/v1.0.0/stac_schema.json
'
# How many URLS above must actually be checked. A literal, compared with the number the loop
# reached: the success line names "both frozen URLs", and a claim in a message is not a check.
FROZEN_URLS=2

SOURCE_FILE=src/stacs/data/receipt/SOURCE

# The temp directory the EXIT handler removes. A GLOBAL, and empty until it exists: a `local`
# inside main() is out of scope by the time the trap fires, so under `set -u` the handler died
# with "tmp: unbound variable" and exit 1 -- after a clean check. One handler, reading globals.
WORK=""
cleanup() { [ -n "$WORK" ] && rm -rf "$WORK"; return 0; }
trap cleanup EXIT

repo_root() {
  cd "$(dirname "$0")/.." && pwd
}

fetch() {
  # fetch <url> <outfile>. An empty file is a failure: a 200 of nothing would diff clean against
  # a vendored file that is also empty.
  curl -sS --fail -L --max-time 120 -o "$2" "$1" || {
    echo "FAIL: could not fetch $1" >&2
    return 1
  }
  [ -s "$2" ] || { echo "FAIL: $1 served an empty file" >&2; return 1; }
}

main() {
  local mode="${1:-}"
  case "$mode" in
    vendor|check) ;;
    *) echo "usage: bash tools/crate_receipt_vendor.sh vendor|check" >&2; exit 2 ;;
  esac

  local root
  root="$(repo_root)"
  cd "$root"

  WORK="$(mktemp -d -t crate_receipt.XXXXXX)"
  [ -n "$WORK" ] || { echo "FAIL: mktemp gave no directory" >&2; exit 1; }
  local tmp="$WORK"

  local bad=0 n=0 src dst

  while read -r src dst; do
    [ -n "${src:-}" ] || continue
    n=$((n + 1))
    mkdir -p "$tmp/$(dirname "$dst")"
    fetch "$RAW/$src" "$tmp/$dst" || { bad=$((bad + 1)); continue; }
    if [ "$mode" = vendor ]; then
      mkdir -p "$(dirname "$dst")"
      cp "$tmp/$dst" "$dst"
      echo "vendored $dst"
    else
      if [ ! -f "$dst" ]; then
        echo "FAIL: $dst is not vendored" >&2
        bad=$((bad + 1))
      elif ! diff -q "$tmp/$dst" "$dst" >/dev/null; then
        echo "FAIL: $dst differs from ${CRATE_REPO}@${CRATE_TAG}:$src" >&2
        bad=$((bad + 1))
      fi
    fi
  done <<EOF
$(printf '%s\n' "$FILES")
EOF

  [ "$n" -gt 0 ] || { echo "FAIL: the file list is empty, so this check would pass on anything" >&2; exit 1; }

  # Counted, because the success line below claims both frozen URLs were checked. Without
  # this, blanking or mangling URLS makes the script exit 0 while asserting it checked them --
  # a guard that fails toward pass, found in review.
  local u=0 url
  while read -r url dst; do
    [ -n "${url:-}" ] || continue
    u=$((u + 1))
    fetch "$url" "$tmp/published" || { bad=$((bad + 1)); continue; }
    if ! diff -q "$tmp/published" "$dst" >/dev/null; then
      echo "FAIL: $url no longer serves the vendored $dst -- a frozen version was edited" >&2
      bad=$((bad + 1))
    fi
  done <<EOF
$(printf '%s\n' "$URLS")
EOF
  [ "$u" -eq "$FROZEN_URLS" ] || {
    echo "FAIL: checked $u frozen URL(s), expected $FROZEN_URLS" >&2
    bad=$((bad + 1))
  }

  # Gated on a clean run: a partially failed vendor used to write a SOURCE claiming the
  # pinned tag for files that kept their old bytes, so the record on disk read as complete
  # even though the script exited 1 (round 3).
  if [ "$mode" = vendor ] && [ "$bad" -eq 0 ]; then
    mkdir -p "$(dirname "$SOURCE_FILE")"
    {
      echo "repo: ${CRATE_REPO}"
      echo "tag: ${CRATE_TAG}"
      echo ""
      echo "The receipt contract, vendored because the test suite is offline. Re-vendor with"
      echo "\`bash tools/crate_receipt_vendor.sh vendor\`; CI runs \`check\` before pytest."
      echo ""
      echo "git blob sha of each file as vendored:"
      while read -r src dst; do
        [ -n "${src:-}" ] || continue
        echo "  $(git hash-object "$dst")  $dst  (<- $src)"
      done <<INNER
$(printf '%s\n' "$FILES")
INNER
    } > "$SOURCE_FILE"
    echo "wrote $SOURCE_FILE"
  fi

  if [ "$bad" -gt 0 ]; then
    echo "$bad problem(s) against ${CRATE_REPO}@${CRATE_TAG}" >&2
    exit 1
  fi
  echo "OK: $n file(s) match ${CRATE_REPO}@${CRATE_TAG}, and both frozen URLs serve them"
}

main "$@"
