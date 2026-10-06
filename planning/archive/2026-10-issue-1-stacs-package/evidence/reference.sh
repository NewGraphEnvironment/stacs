#!/bin/bash
# Reference sets from stac_dem_bc's register_manifest.py (origin/main), read-only.
# Usage: API=<stac api> AIRPHOTO_BUCKET=<url> ELEVATION_BUCKET=<url> reference.sh <out_root>
set -euo pipefail
OUT="$1"
DEM=~/Projects/repo/stac_dem_bc
PY="$DEM/.venv/bin/python"
RM="$DEM/scripts/register_manifest.py"
API="${API:?set API}"
run_one() {
  local cid="$1" bucket="$2" d="$OUT/$1"
  mkdir -p "$d/items"
  local t0; t0=$(date -u +%s)
  echo "== $cid start $(date -u +%FT%TZ)"
  curl -fsSL --max-time 300 "$bucket/collection.json" -o "$d/collection.json"
  "$PY" "$RM" hrefs-published --collection-file "$d/collection.json" > "$d/hrefs.tsv"
  cut -f2 "$d/hrefs.tsv" | sort -u > "$d/urls.txt"
  "$PY" "$RM" fetch-bodies --urls-file "$d/urls.txt" --out-dir "$d/items" \
    --failed-out "$d/failed.txt" --workers 20 2> "$d/fetch_stderr.txt"
  echo "fetched $(find "$d/items" -name '*.json' | wc -l | tr -d ' ') of $(wc -l < "$d/urls.txt" | tr -d ' ')"
  "$PY" "$RM" diff --collection-file "$d/collection.json" --collection-id "$cid" \
    --api "$API" --fetch-dir "$d/items" --missing-out "$d/missing.txt" \
    --orphaned-out "$d/orphaned.txt" --changed-out "$d/changed.txt"
  "$PY" "$RM" collection-state --collection-file "$d/collection.json" \
    --collection-id "$cid" --api "$API" > "$d/collection_state.txt"
  echo "== $cid done in $(( $(date -u +%s) - t0 ))s: missing $(wc -l < "$d/missing.txt" | tr -d ' ') changed $(wc -l < "$d/changed.txt" | tr -d ' ') orphaned $(wc -l < "$d/orphaned.txt" | tr -d ' ') collection $(cat "$d/collection_state.txt")"
}
cd "$DEM"
run_one stac-airphoto-bc "${AIRPHOTO_BUCKET:?}"
run_one stac-elevation-bc "${ELEVATION_BUCKET:?}"
echo "== all done $(date -u +%FT%TZ)"
