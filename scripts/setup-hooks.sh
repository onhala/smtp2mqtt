#!/usr/bin/env bash
# Setup Git Hooks for smtp2mqtt repository
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "⚙️ Nastavuji Git hooks v repozitáři..."
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit

echo "✅ Git pre-commit hook úspěšně aktivován! Při každém 'git commit' se automaticky spustí testy."
