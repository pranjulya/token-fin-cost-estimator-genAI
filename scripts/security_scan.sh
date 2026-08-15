#!/usr/bin/env bash
# Phase 20 security check: dependency audit + committed-secret scan.
set -euo pipefail

echo "== pip-audit =="
uvx pip-audit

echo "== secret scan =="
# Fail if likely secret-bearing files are tracked in git.
if git ls-files | grep -E '(^|/)(\.env$|\.pem$|id_rsa|credentials|\.key$)' ; then
  echo "ERROR: potential secret file tracked in git" >&2
  exit 1
fi

# Fail on obvious API-key / bearer / password literals in tracked source/docs,
# ignoring test fixtures and the seed/README examples that use dev keys.
if git grep -n -E 'sk-[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9]{20,}|password=[A-Za-z0-9]{8,}' -- '*.py' '*.toml' '*.yml' '*.md' ':!tests/*' ':!README.md' ':!scripts/seed_pricing.py' ; then
  echo "ERROR: possible committed secret" >&2
  exit 1
fi

echo "security-check passed"
