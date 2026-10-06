#!/usr/bin/env bash
# Pre-publish sweep. Fails if it finds:
#   1. credential-shaped strings in tracked files;
#   2. credential-shaped strings in any commit in history;
#   3. a tracked .env file;
#   4. any term from .sweep-terms (a local deny-list that is never committed)
#      in tracked files, history, commit messages or author metadata.
# Credential hits are reported by file or commit only, never printed.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

SECRETS='sk-ant-[A-Za-z0-9_-]{20,}|sk_[a-f0-9]{40,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|gh[pousr]_[A-Za-z0-9]{36,}|xox[abpr]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
failed=0

fail() {
  echo "  FAIL: $1"
  failed=1
}

echo "1. Credential-shaped strings in tracked files"
files=$(git grep -lE "$SECRETS" -- . || true)
[[ -n "$files" ]] && fail "found in: $files"

echo "2. Credential-shaped strings in history"
for commit in $(git rev-list --all); do
  if git show --format= "$commit" | grep -qE "$SECRETS"; then
    fail "in commit $(git log -1 --format=%h "$commit")"
  fi
done

echo "3. Tracked .env files"
envs=$(git ls-files | grep -E '(^|/)\.env$' || true)
[[ -n "$envs" ]] && fail "tracked: $envs"

echo "4. Deny-listed terms in tree, history, messages and authors"
if [[ ! -s .sweep-terms ]]; then
  fail ".sweep-terms is missing or empty, so this check cannot run"
else
  git grep -nE -f .sweep-terms -- . && fail "term in tracked files"
  git log --all -p --no-color --format='commit %h%nauthor %an <%ae>%n%B' \
    | grep -nE -f .sweep-terms && fail "term in history or commit metadata"
fi

if ((failed)); then
  echo "Sweep FAILED"
  exit 1
fi
echo "Sweep passed"
