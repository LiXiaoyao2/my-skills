#!/bin/bash
# 拆除 dsh web 的 systemd 自启，回归"需要时手动跑 dsh web"的普通用法。
# 可重复运行：已经拆干净时不会报错退出。
#
# 用法: bash uninstall.sh [--keep-scripts]
#   --keep-scripts  保留 ~/.local/bin 下的 dsh-web-launcher / dsh-web-url
#                   （手动跑 dsh web 时 token 仍然只打印一次，保留它们方便事后取 URL）
set -uo pipefail

BIN_DIR="${DSH_WEB_BIN_DIR:-$HOME/.local/bin}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/dsh-web.service"
STATE_DIR="$HOME/.local/state/dsh-web"
KEEP_SCRIPTS=0
[ "${1:-}" = "--keep-scripts" ] && KEEP_SCRIPTS=1

say() { printf '%s\n' "$*"; }

# ---- 1. 停用并卸载服务 ----
if systemctl --user list-unit-files 2>/dev/null | grep -q '^dsh-web\.service'; then
  systemctl --user disable --now dsh-web.service
  say "==> 已停止并 disable dsh-web.service"
else
  say "==> dsh-web.service 未安装，跳过停止"
fi

# ---- 2. 移走 unit 文件（先备份，不直接删）----
if [ -f "$UNIT" ]; then
  mkdir -p "$STATE_DIR"
  cp -a "$UNIT" "$STATE_DIR/dsh-web.service.bak-$(date +%Y%m%d-%H%M%S)"
  rm -f "$UNIT"
  say "==> 已移除 $UNIT（备份在 $STATE_DIR/）"
fi
systemctl --user daemon-reload
systemctl --user reset-failed dsh-web.service 2>/dev/null || true

# ---- 3. 清脚本 ----
if [ "$KEEP_SCRIPTS" -eq 1 ]; then
  say "==> 按要求保留 $BIN_DIR/dsh-web-launcher 与 dsh-web-url"
else
  for f in "$BIN_DIR/dsh-web-launcher" "$BIN_DIR/dsh-web-url"; do
    [ -f "$f" ] && rm -f "$f" && say "==> 已删除 $f"
  done
  rmdir "$BIN_DIR" 2>/dev/null || true   # 只在空目录时删得掉
fi

# ---- 4. 自检：确认没有残留的自动启动 ----
say ""
say "==> 自检"
if systemctl --user is-enabled dsh-web.service >/dev/null 2>&1; then
  say "    ✗ 仍是 enabled，需要手工排查" >&2
  exit 1
else
  say "    ✓ 已无 enabled 的 dsh-web 单元"
fi
if pgrep -f '[d]sh web' >/dev/null 2>&1; then
  say "    ! 仍有 dsh web 进程在跑（可能是你手动起的，属正常）: $(pgrep -f '[d]sh web' | tr '\n' ' ')"
else
  say "    ✓ 没有 dsh web 进程"
fi
[ -f "$STATE_DIR/url.txt" ] && say "    · 残留状态文件（可删）: $STATE_DIR/url.txt"

say ""
say "==> 完成。以后要用就手动跑，URL 会直接打印在终端里："
say "    dsh web"
say "    然后打开它打印的那条带 ?token= 的地址。"
