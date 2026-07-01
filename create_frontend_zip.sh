#!/usr/bin/env bash
set -e
ROOT_DIR="$(pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
ZIP_FILE="$ROOT_DIR/frontend.zip"

if [ ! -d "$FRONTEND_DIR" ]; then
  echo "frontend 目录不存在: $FRONTEND_DIR"
  exit 1
fi

rm -f "$ZIP_FILE"
cd "$FRONTEND_DIR"
zip -r "$ZIP_FILE" .

echo "Created $ZIP_FILE"
