#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 build_kit_feed.py --kit products.xlsx --output kit_feed.yml --report kit_feed_report.csv
