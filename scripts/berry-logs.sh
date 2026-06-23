#!/usr/bin/env bash
#
# Berry 线上日志查询 — 在本地 Mac 跑,通过 ssh 把生产容器的日志拉回来。
#
# 默认行为:把每行截到 400 字符再 grep,因为 berry 的 wire_id 日志会把
# 完整 LLM payload(几 MB)dump 在一行,直接 grep / tail 会把 SSH 流打爆。
#
# 用法:
#   ./scripts/berry-logs.sh                       # 最近 30 分钟,截行后全打印
#   ./scripts/berry-logs.sh --since 10m           # 改时间窗
#   ./scripts/berry-logs.sh --grep "INTERNAL"     # 只看匹配行(已截行)
#   ./scripts/berry-logs.sh --wire 7daae414       # 看某 wire_id 的 tool_use / stop_reason / 文本预览
#   ./scripts/berry-logs.sh --turns               # 列出最近所有 turn 的 LLM 调用链(每个 turn 一行)
#   ./scripts/berry-logs.sh --raw                 # 不截行,完整原始日志(慎用,可能很大)
#   ./scripts/berry-logs.sh --tail-f              # 实时跟踪(截行 + grep 友好)
#
# 配置(跟 deploy.sh 一致):

set -euo pipefail

SSH_HOST="ubuntu@124.221.210.50"
REMOTE_DIR="~/apps/berry"
COMPOSE_ENV_FILE=".env.production"
SERVICE="berry"

SINCE="30m"
GREP_PATTERN=""
WIRE_ID=""
TURNS_MODE=0
RAW=0
FOLLOW=0
TRUNC=400

while [ $# -gt 0 ]; do
    case "$1" in
        --since)    SINCE="$2"; shift 2 ;;
        --grep)     GREP_PATTERN="$2"; shift 2 ;;
        --wire)     WIRE_ID="$2"; shift 2 ;;
        --turns)    TURNS_MODE=1; shift ;;
        --raw)      RAW=1; shift ;;
        --tail-f)   FOLLOW=1; shift ;;
        --trunc)    TRUNC="$2"; shift 2 ;;
        -h|--help)  sed -n '3,18p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

# Common compose-logs prefix on the remote.
LOG_CMD="docker compose --env-file $COMPOSE_ENV_FILE logs $SERVICE --no-log-prefix"

if [ "$FOLLOW" = "1" ]; then
    # tail -f 模式:实时,截行后 grep。
    FILTER='cat'
    [ -n "$GREP_PATTERN" ] && FILTER="grep -aE '$GREP_PATTERN'"
    ssh -o StrictHostKeyChecking=no "$SSH_HOST" \
        "cd $REMOTE_DIR && $LOG_CMD --tail 0 --follow 2>&1 | awk '{print substr(\$0,1,$TRUNC)}' | $FILTER"
    exit $?
fi

if [ "$TURNS_MODE" = "1" ]; then
    # Turn 视图:解析每个 wire_id 响应,提取 tool_use / stop_reason / 文本前 80 字。
    # 在远端用 python3 解析以避免拉回大日志。
    ssh -o StrictHostKeyChecking=no "$SSH_HOST" \
        "cd $REMOTE_DIR && $LOG_CMD --since $SINCE 2>&1 > /tmp/berry-logs-tmp.txt && python3 - <<'PY'
import json
with open('/tmp/berry-logs-tmp.txt') as f:
    for line in f:
        line = line.strip()
        if '\"wire_id\"' not in line or '\"duration_ms\"' not in line:
            continue
        if '\"mode\": \"stream\"' not in line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        wid = d.get('wire_id', '?')[:12]
        dur = d.get('duration_ms', '?')
        tool_uses, stop_reasons, chunks = [], [], []
        for ev in d.get('payload', {}).get('events', []):
            t = ev.get('type')
            if t == 'content_block_start':
                cb = ev.get('content_block', {})
                if cb.get('type') == 'tool_use':
                    tool_uses.append(cb.get('name'))
            elif t == 'message_delta':
                sr = ev.get('delta', {}).get('stop_reason')
                if sr:
                    stop_reasons.append(sr)
            elif t == 'content_block_delta':
                dd = ev.get('delta', {})
                if dd.get('type') == 'text_delta' and dd.get('text'):
                    chunks.append(dd['text'])
        text = ''.join(chunks)[:80].replace('\n', ' ')
        sr = ','.join(stop_reasons) or '?'
        tu = ','.join(tool_uses) or '-'
        print(f'{wid} {dur:>6}ms stop={sr:<10} tools=[{tu}]  {text}')
PY"
    exit $?
fi

if [ -n "$WIRE_ID" ]; then
    # 单 wire_id 详情:dump 所有 tool_use args + 完整文本。
    ssh -o StrictHostKeyChecking=no "$SSH_HOST" \
        "cd $REMOTE_DIR && $LOG_CMD --since $SINCE 2>&1 > /tmp/berry-logs-tmp.txt && python3 - <<PY
import json
with open('/tmp/berry-logs-tmp.txt') as f:
    for line in f:
        if '$WIRE_ID' not in line or '\"duration_ms\"' not in line:
            continue
        try:
            d = json.loads(line.strip())
        except Exception:
            continue
        print('=== wire_id $WIRE_ID ===')
        print(f'duration_ms: {d.get(\"duration_ms\")}')
        print(f'event_count: {d.get(\"event_count\")}')
        chunks, tool_uses = [], []
        for ev in d.get('payload', {}).get('events', []):
            t = ev.get('type')
            if t == 'content_block_start':
                cb = ev.get('content_block', {})
                if cb.get('type') == 'tool_use':
                    tool_uses.append({'name': cb.get('name'), 'id': cb.get('id')})
            elif t == 'content_block_delta':
                dd = ev.get('delta', {})
                if dd.get('type') == 'text_delta':
                    chunks.append(dd.get('text', ''))
                elif dd.get('type') == 'input_json_delta':
                    if tool_uses:
                        tool_uses[-1].setdefault('input', '')
                        tool_uses[-1]['input'] += dd.get('partial_json', '')
        print(f'tool_uses: {tool_uses}')
        print('--- assistant text ---')
        print(''.join(chunks))
        break
PY"
    exit $?
fi

if [ "$RAW" = "1" ]; then
    if [ -n "$GREP_PATTERN" ]; then
        ssh -o StrictHostKeyChecking=no "$SSH_HOST" \
            "cd $REMOTE_DIR && $LOG_CMD --since $SINCE 2>&1 | grep -aE '$GREP_PATTERN'"
    else
        ssh -o StrictHostKeyChecking=no "$SSH_HOST" \
            "cd $REMOTE_DIR && $LOG_CMD --since $SINCE 2>&1"
    fi
    exit $?
fi

# Default: 截行 + 可选 grep。
if [ -n "$GREP_PATTERN" ]; then
    ssh -o StrictHostKeyChecking=no "$SSH_HOST" \
        "cd $REMOTE_DIR && $LOG_CMD --since $SINCE 2>&1 | awk '{print substr(\$0,1,$TRUNC)}' | grep -aE '$GREP_PATTERN'"
else
    ssh -o StrictHostKeyChecking=no "$SSH_HOST" \
        "cd $REMOTE_DIR && $LOG_CMD --since $SINCE 2>&1 | awk '{print substr(\$0,1,$TRUNC)}'"
fi
