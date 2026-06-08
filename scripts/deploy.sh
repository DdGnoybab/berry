#!/usr/bin/env bash
#
# Berry 一键部署 — 在本地 Mac 跑,通过 ssh 把代码部署到服务器。
#
# 用法:
#   ./scripts/deploy.sh                    # 推 origin/main 上的最新提交
#   ./scripts/deploy.sh --force-build      # 强制重 build(忽略变更检测)
#   ./scripts/deploy.sh --dry-run          # 演练,只打印不执行
#   ./scripts/deploy.sh --rollback         # 立即回滚到上一个已知健康的版本
#
# 工作流(对应你 4 个选择):
#   1. 检查本地分支同步状态,确保 origin/main 有最新代码
#   2. ssh 到服务器,git pull,记录"上一个 commit"作为回滚锚点
#   3. 智能判断:
#      - Dockerfile / pyproject.toml / web/package*.json 改了 → build
#      - 否则跳过 build
#   4. 智能判断:
#      - alembic/versions/ 新增文件 → 跑迁移
#      - 否则跳过迁移
#   5. 重启 berry(zero-downtime 不在 MVP 范围,简单先 down/up)
#   6. 健康检查:curl /v1/methods,30 秒内 200 才算成功
#   7. 任意一步失败 → git reset --hard 回到部署前的 commit + 重启旧镜像
#
# 配置在脚本顶部,按你环境改。

set -euo pipefail

# ─── 配置 ─────────────────────────────────────
SSH_HOST="ubuntu@124.221.210.50"
REMOTE_DIR="~/apps/berry"
COMPOSE_ENV_FILE=".env.production"
HEALTH_URL="http://localhost/v1/methods"
HEALTH_TIMEOUT=30           # 健康检查最长等待秒数
HEALTH_INTERVAL=2           # 每多少秒查一次
LOCAL_BRANCH="main"
# ──────────────────────────────────────────────

# 颜色输出(简单美化)
red()    { printf "\033[31m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
blue()   { printf "\033[34m%s\033[0m\n" "$*"; }
bold()   { printf "\033[1m%s\033[0m\n" "$*"; }

# 解析参数
FORCE_BUILD=0
DRY_RUN=0
ROLLBACK=0
for arg in "$@"; do
    case "$arg" in
        --force-build) FORCE_BUILD=1 ;;
        --dry-run)     DRY_RUN=1 ;;
        --rollback)    ROLLBACK=1 ;;
        -h|--help)
            sed -n '3,20p' "$0"
            exit 0
            ;;
        *) red "Unknown arg: $arg"; exit 2 ;;
    esac
done

# 包装 ssh,统一参数
remote() {
    if [ "$DRY_RUN" = "1" ]; then
        yellow "  [dry-run] ssh $SSH_HOST '$*'"
        return 0
    fi
    ssh -o StrictHostKeyChecking=no "$SSH_HOST" "cd $REMOTE_DIR && $*"
}

# 远程执行但要捕获输出
remote_capture() {
    ssh -o StrictHostKeyChecking=no "$SSH_HOST" "cd $REMOTE_DIR && $*"
}

dc() {
    # 远程跑 docker compose,自动带 --env-file
    remote "docker compose --env-file $COMPOSE_ENV_FILE $*"
}

# ─── 回滚:专门的入口 ────────────────────────
do_rollback() {
    bold "▶ 回滚模式"

    local last_good
    last_good=$(remote_capture "cat .deploy_last_good 2>/dev/null || true")
    if [ -z "$last_good" ]; then
        red "✗ 找不到 .deploy_last_good 锚点文件,没有可回滚的版本"
        exit 1
    fi

    yellow "  上一个健康版本:$last_good"
    read -p "  确认回滚到这个版本?(y/N) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && { yellow "  取消"; exit 0; }

    rollback_to "$last_good"
}

# ─── 回滚执行 ────────────────────────────────
rollback_to() {
    local target_commit="$1"
    yellow "  回滚到 $target_commit"
    remote "git reset --hard $target_commit"
    # 旧镜像本地缓存里通常还在,直接 up 即可;如果丢了就重 build
    if ! dc "up -d"; then
        yellow "  容器重启失败,尝试重 build 旧版本"
        dc "build berry"
        dc "up -d"
    fi
    red "✗ 已回滚到 $target_commit"
}

# ─── 主流程 ────────────────────────────────
[ "$ROLLBACK" = "1" ] && { do_rollback; exit 0; }

bold "▶ Berry 部署"
[ "$DRY_RUN" = "1" ] && yellow "  ⚠ DRY-RUN 模式 — 只打印不执行"

# Step 1: 检查本地状态
blue "[1/7] 检查本地仓库状态..."
LOCAL_DIRTY=$(git status --porcelain)
if [ -n "$LOCAL_DIRTY" ]; then
    red "✗ 本地有未提交改动,请先 commit 或 stash:"
    echo "$LOCAL_DIRTY"
    exit 1
fi

git fetch origin "$LOCAL_BRANCH" --quiet
LOCAL_SHA=$(git rev-parse "$LOCAL_BRANCH")
ORIGIN_SHA=$(git rev-parse "origin/$LOCAL_BRANCH")
if [ "$LOCAL_SHA" != "$ORIGIN_SHA" ]; then
    red "✗ 本地 $LOCAL_BRANCH ($LOCAL_SHA) 与 origin/$LOCAL_BRANCH ($ORIGIN_SHA) 不同步"
    yellow "  请先 git push 或 git pull --rebase"
    exit 1
fi
green "  ✓ 本地与 origin/$LOCAL_BRANCH 同步:$LOCAL_SHA"

# Step 2: 拉远程当前状态作为回滚锚点
blue "[2/7] 记录回滚锚点..."
PREV_COMMIT=$(remote_capture "git rev-parse HEAD")
green "  ✓ 当前服务器 HEAD:$PREV_COMMIT"

# Step 3: 远程 git pull
blue "[3/7] 拉取代码..."
remote "git fetch --quiet && git reset --hard origin/$LOCAL_BRANCH"
NEW_COMMIT=$(remote_capture "git rev-parse HEAD")
if [ "$NEW_COMMIT" = "$PREV_COMMIT" ]; then
    yellow "  ⓘ 没有新提交,部署啥也不会变。继续(走一遍重启刷新)。"
else
    green "  ✓ HEAD 变成:$NEW_COMMIT"
    yellow "  改动文件:"
    remote "git --no-pager diff --name-only $PREV_COMMIT $NEW_COMMIT" | sed 's/^/    /'
fi

# Step 4: 智能 build
blue "[4/7] 判断是否需要重 build..."
NEED_BUILD=0
if [ "$FORCE_BUILD" = "1" ]; then
    yellow "  --force-build,强制重 build"
    NEED_BUILD=1
elif [ "$NEW_COMMIT" = "$PREV_COMMIT" ]; then
    yellow "  ⓘ 没有新提交,跳过 build"
else
    # 任何会被 COPY 进镜像的文件改了都要重 build。
    # 源码目录用前缀匹配(berry/ web/ config/),配置/依赖文件用全名匹配。
    # 注意:berry/ 只匹配 berry/<...> 不会误中根目录 berry 单文件,因为我们用 ^ 锚定。
    BUILD_TRIGGER_PATTERN='^(Dockerfile|deploy/Dockerfile\.web|deploy/nginx\.conf|pyproject\.toml|uv\.lock|berry/.+|config/.+|web/.+)$'
    CHANGED=$(remote_capture "git diff --name-only $PREV_COMMIT $NEW_COMMIT | grep -E '$BUILD_TRIGGER_PATTERN' || true")
    if [ -n "$CHANGED" ]; then
        green "  ✓ 检测到依赖文件变化,需要 build:"
        echo "$CHANGED" | sed 's/^/    /'
        NEED_BUILD=1
    else
        yellow "  ⓘ 没有依赖文件变化,跳过 build"
    fi
fi

if [ "$NEED_BUILD" = "1" ]; then
    blue "      执行 docker compose build..."
    dc "build" || { red "✗ build 失败,触发回滚"; rollback_to "$PREV_COMMIT"; exit 1; }
    green "  ✓ build 完成"
fi

# Step 5: 智能迁移
blue "[5/7] 判断是否需要跑迁移..."
NEED_MIGRATE=0
if [ "$NEW_COMMIT" = "$PREV_COMMIT" ]; then
    yellow "  ⓘ 没有新提交,跳过迁移检测"
else
    NEW_MIGRATIONS=$(remote_capture "git diff --name-only --diff-filter=A $PREV_COMMIT $NEW_COMMIT -- alembic/versions/ || true")
    if [ -n "$NEW_MIGRATIONS" ]; then
        green "  ✓ 检测到新增迁移:"
        echo "$NEW_MIGRATIONS" | sed 's/^/    /'
        NEED_MIGRATE=1
    else
        yellow "  ⓘ 没有新增迁移,跳过 alembic"
    fi
fi

if [ "$NEED_MIGRATE" = "1" ]; then
    blue "      执行 alembic upgrade head..."
    dc "run --rm berry alembic upgrade head" || { red "✗ 迁移失败,触发回滚"; rollback_to "$PREV_COMMIT"; exit 1; }
    green "  ✓ 迁移完成"
fi

# Step 6: 重启
blue "[6/7] 重启服务..."
dc "up -d" || { red "✗ 重启失败,触发回滚"; rollback_to "$PREV_COMMIT"; exit 1; }
green "  ✓ 容器已 up"

# Step 7: 健康检查
blue "[7/7] 健康检查 (最长 ${HEALTH_TIMEOUT}s)..."
WAITED=0
HEALTHY=0
while [ $WAITED -lt $HEALTH_TIMEOUT ]; do
    HTTP_CODE=$(remote_capture "curl -s -o /dev/null -w '%{http_code}' $HEALTH_URL || echo 000")
    if [ "$HTTP_CODE" = "200" ]; then
        HEALTHY=1
        break
    fi
    printf "  等待中... %ds (HTTP %s)\r" "$WAITED" "$HTTP_CODE"
    sleep "$HEALTH_INTERVAL"
    WAITED=$((WAITED + HEALTH_INTERVAL))
done
echo

if [ "$HEALTHY" = "1" ]; then
    green "  ✓ 健康检查通过 (HTTP 200)"
    # 记录这次部署作为下一次的回滚锚点
    remote "echo $NEW_COMMIT > .deploy_last_good"
    bold ""
    green "✅ 部署成功 → $NEW_COMMIT"
    bold ""
else
    red "  ✗ 健康检查超时,触发回滚"
    remote "docker compose --env-file $COMPOSE_ENV_FILE logs berry --tail 30" || true
    rollback_to "$PREV_COMMIT"
    exit 1
fi
