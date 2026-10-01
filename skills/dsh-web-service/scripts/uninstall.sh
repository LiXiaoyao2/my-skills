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
BASE_PORT="${DSH_WEB_BASE_PORT:-3080}"
KEEP_SCRIPTS=0
[ "${1:-}" = "--keep-scripts" ] && KEEP_SCRIPTS=1

say() { printf '%s\n' "$*"; }

# ---- 1. 停用并卸载服务 ----
# 不要用 `systemctl ... | grep -q` 判断单元在不在：
# set -o pipefail 下 grep -q 命中即退出，会让上游 systemctl 收到 SIGPIPE(141)，
# 整条管道被判失败，条件随机为假（实测同一段连跑六次：FTFFTF）。
# 后果是"没停服务就把 unit 删了"，留下一只占着端口的孤儿进程。
# 这里改成不经过管道的判断。
unit_known=0
[ -f "$UNIT" ] && unit_known=1
systemctl --user is-enabled dsh-web.service >/dev/null 2>&1 && unit_known=1
systemctl --user is-active --quiet dsh-web.service && unit_known=1

if [ "$unit_known" -eq 1 ]; then
  systemctl --user disable --now dsh-web.service || true
  # 等它真的退干净，否则下一步删完文件才发现自己还占着端口
  for _ in $(seq 1 20); do
    systemctl --user is-active --quiet dsh-web.service || break
    sleep 0.5
  done
  say "==> 已停止并 disable dsh-web.service"
else
  say "==> dsh-web.service 本就未启用，跳过停止"
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

# 单元没了但进程还在 = 孤儿，它会继续占端口，导致下次手动 dsh web 撞 EADDRINUSE。
# 不要用 `pgrep -f "dsh web"` 来找：pgrep 只排除自己，不排除祖先 shell，
# 而调用者的命令行里通常就含 "dsh web"（比如刚手动敲过），于是把自己的父 shell
# 误报成孤儿。改成看端口：谁在听 dsh 可能用的端口，再去 /proc 查它到底是不是 dsh。
dsh_holders=""
busy_ports=""
for p in $(seq "$BASE_PORT" $((BASE_PORT + 19))); do
  holders=$(ss -H -ltnp "sport = :$p" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u)
  [ -z "$holders" ] && continue
  busy_ports="$busy_ports $p"
  for pid in $holders; do
    cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
    case "$cmd" in
      *dsh\ web*|*dsh-web-launcher*) dsh_holders="$dsh_holders $pid" ;;
    esac
  done
done

if [ -n "${dsh_holders// /}" ]; then
  say "    ! dsh 进程仍在运行: $dsh_holders" >&2
  say "      它会一直占着端口，下次手动 dsh web 会报 EADDRINUSE。停掉它:" >&2
  say "        kill $dsh_holders" >&2
else
  say "    ✓ 没有 dsh web / launcher 进程"
fi
[ -n "${busy_ports// /}" ] && say "    · 端口$busy_ports 仍被占用（不是 dsh 的话属正常）"
[ -f "$STATE_DIR/url.txt" ] && say "    · 残留状态文件（可删）: $STATE_DIR/url.txt"

say ""
say "==> 完成。以后要用就手动跑，URL 会直接打印在终端里："
say "    dsh web"
say "    然后打开它打印的那条带 ?token= 的地址。"
