#!/bin/bash
# 安装 dsh web 的 systemd 用户服务（开机自启 + 端口避让 + token URL 落盘）。
# 可重复运行：重跑会覆盖脚本与 unit 并重启服务。
#
# 用法: bash install.sh
#   环境变量:
#     DSH_WEB_BASE_PORT  起始端口，默认 3080
#     DSH_WEB_URL_FILE   token URL 落盘位置，默认 ~/.local/state/dsh-web/url.txt
set -euo pipefail

S_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${DSH_WEB_BIN_DIR:-$HOME/.local/bin}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/dsh-web.service"
STATE_DIR="$HOME/.local/state/dsh-web"
URL_FILE="${DSH_WEB_URL_FILE:-$STATE_DIR/url.txt}"
BASE_PORT="${DSH_WEB_BASE_PORT:-3080}"

say() { printf '%s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

# ---- 1. 定位 dsh ----
DSH_BIN="${DSH_BIN:-$(command -v dsh 2>/dev/null || true)}"
[ -n "$DSH_BIN" ] && [ -x "$DSH_BIN" ] || die "PATH 里找不到 dsh。先装好 dsh，或用 DSH_BIN=/abs/path 指定。"
DSH_BIN="$(readlink -f "$DSH_BIN")"

# dsh 的 shebang 是 #!/usr/bin/env node，而 systemd 不加载 nvm 的 shell 配置，
# 所以 unit 里必须显式给出含 node 的 PATH，否则报 env: node: No such file or directory
NODE_BIN="$(command -v node 2>/dev/null || true)"
[ -n "$NODE_BIN" ] || die "找不到 node。dsh 是 node 程序，必须有 node 才能跑。"
NODE_DIR="$(dirname "$(readlink -f "$NODE_BIN")")"

say "==> dsh:    $DSH_BIN"
say "==> node:   $NODE_BIN"
say "==> 端口:   $BASE_PORT（被占用时自动往后找）"
say "==> URL:    $URL_FILE"

# ---- 2. 装脚本 ----
mkdir -p "$BIN_DIR" "$UNIT_DIR" "$STATE_DIR"
install -m 0755 "$S_DIR/dsh-web-launcher" "$BIN_DIR/dsh-web-launcher"
install -m 0755 "$S_DIR/dsh-web-url"     "$BIN_DIR/dsh-web-url"
say "==> 已安装 $BIN_DIR/dsh-web-launcher, $BIN_DIR/dsh-web-url"

# ---- 3. 写 unit ----
# 注意几处不是"风格问题"，改错会直接导致故障：
#   Environment=PATH  —— 缺 nvm 路径就找不到 node
#   Environment=DSH_BIN —— launcher 需要它，且不依赖 unit 的 PATH
#   StandardOutput=journal —— 启动时打印的 token URL 只有 journal 里找得到
#   KillMode=mixed + ExecStop —— SIGTERM 只到 MainID(=launcher)，由 launcher 转发给 node
cat > "$UNIT" <<EOF
[Unit]
Description=DeepSeek Harness Web (dsh web) — systemd 用户服务
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$HOME
Environment=NODE_ENV=production
Environment=DSH_HOME=$HOME/.dsh
Environment=PATH=$NODE_DIR:$BIN_DIR:/usr/local/bin:/usr/bin:/bin
Environment=DSH_BIN=$DSH_BIN
Environment=DSH_WEB_BASE_PORT=$BASE_PORT
Environment=DSH_WEB_URL_FILE=$URL_FILE
ExecStart=$BIN_DIR/dsh-web-launcher
ExecStop=/bin/kill -TERM \$MAINPID
Restart=always
RestartSec=3
TimeoutStopSec=20
KillSignal=SIGTERM
KillMode=mixed
StandardOutput=journal
StandardError=journal
SyslogIdentifier=dsh-web

[Install]
WantedBy=default.target
EOF
say "==> 已写入 $UNIT"

# ---- 4. 启用并启动 ----
systemctl --user daemon-reload
systemctl --user enable --now dsh-web.service
say "==> 服务已 enable --now"

# ---- 5. 等 token URL 落盘 ----
for _ in $(seq 1 30); do
  sleep 1
  [ -s "$URL_FILE" ] && grep -aq 'token=' "$URL_FILE" 2>/dev/null && break
done

if systemctl --user is-active --quiet dsh-web.service; then
  ACTIVE_PORT="$(ss -H -ltnp "sport = :$BASE_PORT" 2>/dev/null | grep -o "127.0.0.1:[0-9]*" | head -1)"
  say "==> 运行中"
else
  say "==> 警告：服务当前不是 active，看日志: journalctl --user-unit dsh-web -b -n 50" >&2
fi

URL="$($BIN_DIR/dsh-web-url 2>/dev/null || true)"
if [ -n "$URL" ]; then
  say ""
  say "    访问地址（先打开这个一次，之后裸地址免 token 30 天）:"
  say "    $URL"
  say ""
  say "    以后随时再取: dsh-web-url        直接开浏览器: dsh-web-url --open"
else
  say "==> 还没拿到 URL，查: journalctl --user-unit dsh-web -b | grep -a 'dsh web:'" >&2
fi
