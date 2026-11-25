#!/usr/bin/env bash
# Render build: install Python dependencies, build the React app, place it where the backend serves it, collect static files.
set -euo pipefail
cd "$(dirname "$0")"

echo "== Python dependencies"
pip install --upgrade pip
pip install -r backend/requirements.txt

echo "== Node (build tooling only)"
if ! command -v node >/dev/null 2>&1; then
  NODE_VERSION="22.11.0"
  curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" -o /tmp/node.tar.xz
  mkdir -p "$HOME/node" && tar -xJf /tmp/node.tar.xz -C "$HOME/node" --strip-components=1
  export PATH="$HOME/node/bin:$PATH"
fi
node --version

echo "== Website (React)"
( cd frontend && npm ci && npm run build )
rm -rf backend/spa backend/spa_index.html
cp -r frontend/dist backend/spa
mv backend/spa/index.html backend/spa_index.html   # served by the backend with runtime settings, not by WhiteNoise

echo "== Static files"
( cd backend && python manage.py collectstatic --noinput )
echo "== Build finished"
