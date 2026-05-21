#!/usr/bin/env bash
# Apply canonical labels from .github/labels.yml using gh CLI.
# Idempotent: --force updates existing labels.
#
# Usage:
#   scripts/setup-labels.sh <owner/repo>
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <owner/repo>" >&2
  exit 2
fi

REPO="$1"
LABELS_FILE=".github/labels.yml"

if ! command -v yq >/dev/null 2>&1; then
  echo "yq required (https://github.com/mikefarah/yq)" >&2
  exit 1
fi

count=$(yq '. | length' "$LABELS_FILE")
for i in $(seq 0 $((count - 1))); do
  name=$(yq ".[$i].name" "$LABELS_FILE")
  color=$(yq ".[$i].color" "$LABELS_FILE")
  desc=$(yq ".[$i].description" "$LABELS_FILE")
  gh label create "$name" --color "$color" --description "$desc" --repo "$REPO" --force >/dev/null
done
echo "Applied $count labels to $REPO"
