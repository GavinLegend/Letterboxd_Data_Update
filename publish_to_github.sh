#!/bin/zsh
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: ./publish_to_github.sh https://github.com/<user>/<repo>.git"
  exit 1
fi

REMOTE_URL="$1"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$REPO_DIR"

if [[ ! -d .git ]]; then
  git init
fi

git checkout -B main
git add .

if ! git diff --cached --quiet; then
  git commit -m "Deploy Letterboxd custom report"
fi

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

git push -u origin main

cat <<'EOF'

Push complete.

Next, in your GitHub repository:
1. Open Settings -> Pages
2. Under "Build and deployment", choose "Deploy from a branch"
3. Select branch "main" and folder "/ (root)"
4. Save

GitHub will then publish the site and give you a public URL.
EOF
