#!/bin/bash
# Commit and push all local changes to GitHub
# Usage: bash commit-push.sh "your commit message"

set -e

cd "/Users/gab/Cursor Projects/Odoo14"

# Require a commit message
if [ -z "$1" ]; then
  echo "Error: please provide a commit message."
  echo "Usage: bash commit-push.sh \"fix: description\""
  exit 1
fi

# Make sure we are on main before pushing
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "main" ]; then
  echo "Error: you are on branch '$BRANCH', not 'main'. Aborting."
  exit 1
fi

echo ">>> Checking status..."
git status

echo ">>> Staging all changes (new, modified, deleted)..."
git add -A

# If nothing to commit, exit cleanly
if git diff --cached --quiet; then
  echo "Nothing to commit — working tree is clean."
  exit 0
fi

echo ">>> Committing..."
git commit -m "$1"

echo ">>> Pushing to GitHub..."
git push origin main

echo ""
echo "Done. Run 'bash deploy-live.sh' to deploy to the live server."
