#!/usr/bin/env bash
# 把本仓库推到 GitHub。
#   用法: bash scripts/push_to_github.sh [owner] [repo]
#   默认: thinkingstill/company-teardown
#
# 逻辑：先看远端仓库是否存在。存在则直接 push（contents 权限足够）；
# 不存在则尝试用 API 创建，若因 token 缺 Administration:write 被拒，
# 打印唯一可行的两条路径，不做无意义的反复重试。

set -uo pipefail
OWNER="${1:-thinkingstill}"
REPO="${2:-company-teardown}"
cd "$(dirname "$0")/.."

# 1. 取 token（连接器把它写进了 shell 配置）
if [ -z "${GITHUB_TOKEN:-}" ]; then
  if grep -q '^export GITHUB_TOKEN=' "$HOME/.zshrc" 2>/dev/null; then
    GITHUB_TOKEN=$(grep '^export GITHUB_TOKEN=' "$HOME/.zshrc" | sed 's/^export GITHUB_TOKEN="//; s/"$//')
  elif [ -f "$(dirname "$0")/../../.codebuddy/skills/github-connector/scripts/get_token.sh" ]; then
    source "$(dirname "$0")/../../.codebuddy/skills/github-connector/scripts/get_token.sh" github >/dev/null
  fi
fi
if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "[FAIL] 找不到 GITHUB_TOKEN。请先在 CodeBuddy 中连接 GitHub 连接器。"
  exit 2
fi

API="https://api.github.com"
AUTH=(-H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json")

# 2. 远端仓库是否已存在
code=$(curl -s -o /dev/null -w "%{http_code}" "${AUTH[@]}" "$API/repos/$OWNER/$REPO")
echo "[INFO] 检查 $OWNER/$REPO → HTTP $code"

if [ "$code" = "404" ]; then
  echo "[INFO] 仓库不存在，尝试创建…"
  body=$(curl -s -X POST "${AUTH[@]}" "$API/user/repos" \
    -d "{\"name\":\"$REPO\",\"description\":\"A股上市公司商业模式拆解：服务领域 × 货币化引擎 × 付费对象 × 时间\",\"private\":false,\"has_issues\":true,\"has_projects\":true}")
  if echo "$body" | grep -q '"full_name"'; then
    echo "[OK] 仓库已创建"
  else
    echo "[FAIL] 创建被拒：$(echo "$body" | tr -d '\n' | head -c 200)"
    cat <<'TIP'

当前 token 是 GitHub App 的细粒度凭证，只有 contents:write，没有账号级的
Administration:write，因此无法创建新仓库。两条可行路径（任选其一）：

  A. 网页建空仓库（30 秒，推荐）
     打开 https://github.com/new
     Repository name 填 company-teardown
     选 Public，不要勾选 Add a README / .gitignore / license
     点 Create repository，然后回来重跑本脚本。

  B. 重新授权连接器
     在 CodeBuddy 设置 → 连接器 → GitHub 中重新授权，
     授权时勾选 repo（含 public_repo 与创建仓库的权限），再重跑本脚本。
TIP
    exit 3
  fi
fi

# 3. 推送
git remote remove origin 2>/dev/null
git remote add origin "https://x-access-token:$GITHUB_TOKEN@github.com/$OWNER/$REPO.git"
echo "[INFO] 推送到 $OWNER/$REPO …"
if git push -u origin HEAD:main 2>&1 | tail -5; then
  echo "[OK] https://github.com/$OWNER/$REPO"
else
  echo "[WARN] push 未成功。若远端已有提交，先执行 git pull --rebase origin main 再重试。"
  exit 4
fi

cat <<'NEXT'

后续两步（只需做一次）：
  1. 开启 Pages：仓库 Settings → Pages → Source 选 GitHub Actions
     之后每次 push 到 main，.github/workflows/pages.yml 会自动构建并发布
  2. 项目看板：仓库 Projects 标签页 → New project → 导入 PROJECT.md 的表格
NEXT
