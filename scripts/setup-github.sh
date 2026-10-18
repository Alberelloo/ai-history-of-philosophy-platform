#!/usr/bin/env bash
# Одноразовая настройка GitHub-репозитория под процесс из docs/process/git-workflow.md.
# Нужны gh (gh auth login) и права администратора репозитория.
# Запуск: bash scripts/setup-github.sh [owner/repo]
set -euo pipefail

repo="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"

# Только squash, сообщение коммита = заголовок и описание PR, ветка удаляется после слияния.
gh api -X PATCH "repos/$repo" \
  -F allow_auto_merge=true \
  -F allow_squash_merge=true \
  -F allow_merge_commit=false \
  -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true \
  -f squash_merge_commit_title=PR_TITLE \
  -f squash_merge_commit_message=PR_BODY >/dev/null

# main: только через PR, слияние после зелёных checks и pr-format, без обязательного ревью.
gh api -X PUT "repos/$repo/branches/main/protection" --input - >/dev/null <<'JSON'
{
  "required_status_checks": {
    "strict": false,
    "checks": [{"context": "checks"}, {"context": "pr-format"}]
  },
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "enforce_admins": false,
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON

echo "Готово: $repo настроен"
