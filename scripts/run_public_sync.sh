#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USERNAME="${1:-goorison}"
OUTPUT_INPUT_DIR="${2:-$ROOT_DIR/data/public-sync/input}"
OUTPUT_CACHE_DIR="${3:-$ROOT_DIR/data/public-sync/cache}"
OUTPUT_REPORT_DIR="${4:-$ROOT_DIR/outputs/public-sync-report}"
VENDOR_DIR="$ROOT_DIR/.vendor"

mkdir -p "$VENDOR_DIR" "$OUTPUT_INPUT_DIR" "$OUTPUT_CACHE_DIR" "$OUTPUT_REPORT_DIR"

python3 -m pip install --quiet --target "$VENDOR_DIR" pandas numpy lxml curl_cffi openpyxl

PYTHONPATH="$VENDOR_DIR${PYTHONPATH:+:$PYTHONPATH}" \
  python3 "$ROOT_DIR/scripts/sync_letterboxd_public.py" \
  --username "$USERNAME" \
  --output-dir "$OUTPUT_INPUT_DIR" \
  --cache-dir "$OUTPUT_CACHE_DIR" \
  --workers 6 \
  --refresh-recent 60

PYTHONPATH="$VENDOR_DIR${PYTHONPATH:+:$PYTHONPATH}" \
  python3 "$ROOT_DIR/scripts/build_custom_letterboxd_report.py" \
  --input-dir "$OUTPUT_INPUT_DIR" \
  --output-dir "$OUTPUT_REPORT_DIR" \
  --streaming-lookups 200 \
  --streaming-workers 3 \
  --douban-lookups 40 \
  --streaming-catalog-timeout 120

cp "$OUTPUT_REPORT_DIR/share-site/index.html" "$ROOT_DIR/index.html"
cp "$OUTPUT_REPORT_DIR/share-site/custom-report-data.json" "$ROOT_DIR/custom-report-data.json"
cp "$OUTPUT_REPORT_DIR/share-site/.nojekyll" "$ROOT_DIR/.nojekyll"

echo "Updated:"
echo "  $ROOT_DIR/index.html"
echo "  $ROOT_DIR/custom-report-data.json"
