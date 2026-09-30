#!/usr/bin/env bash
#
# Launch a built AppImage and check that it actually came up.
#
# What this can prove: the Electron process tree spawned, a renderer process
# exists (so a window was created and is rendering), the bundled Host answered
# on its port, and the app reached DeepSeek's account API.
#
# What it cannot prove: that the window looks right. On a native Wayland
# session the window is not an X11 window, so xdotool/wmctrl/import will not see
# it. Say so rather than implying the UI was inspected.
#
# Usage: verify-appimage.sh [path-to-AppImage]

set -uo pipefail

APPIMAGE="${1:-/home/lin/DeepSeek-Harness-0.2.0-rc.2-linux-x86_64.AppImage}"
LOG="/tmp/dsh-appimage-verify.log"
PORT=19387   # Desktop default; the Web UI uses 3080, so they don't collide

[ -f "$APPIMAGE" ] || { echo "✗ 找不到 $APPIMAGE" >&2; exit 1; }
chmod +x "$APPIMAGE"

# The AppImage mount path is randomised per run; match on a bracket class so the
# pgrep pattern never matches this script's own command line.
running() { pgrep -f "mount_Deep[S]" >/dev/null 2>&1; }

if running; then
  echo "已有实例在运行，先停止："
  pgrep -f "mount_Deep[S]" | while read -r pid; do kill "$pid" 2>/dev/null; done
  sleep 3
fi

echo "启动 $APPIMAGE"
export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
nohup "$APPIMAGE" > "$LOG" 2>&1 &
sleep 40

fail=0
check() {
  if [ "$2" -gt 0 ] 2>/dev/null; then printf '  ✓ %s\n' "$1"
  else printf '  ✗ %s\n' "$1"; fail=1; fi
}

echo
echo "检查："
check "主进程存活"          "$(pgrep -cf 'mount_Deep[S]')"
check "渲染进程存在（窗口已创建）" "$(pgrep -f 'mount_Deep[S].*type=renderer' | wc -l)"
check "GPU 进程存在"        "$(pgrep -f 'mount_Deep[S].*type=gpu-process' | wc -l)"
check "内嵌 dsh 运行时"     "$(pgrep -f 'mount_Deep[S].*dsh' | wc -l)"

code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null)
if [ "$code" = "401" ] || [ "$code" = "200" ]; then
  echo "  ✓ Host 响应 http://127.0.0.1:$PORT (HTTP $code)"
else
  echo "  ✗ Host 无响应 (HTTP $code)"; fail=1
fi

if grep -qE "\[deepseek-account\].*status: 200" "$LOG" 2>/dev/null; then
  echo "  ✓ 已连通 DeepSeek 账号 API"
else
  echo "  · 未见账号 API 成功响应（未登录时属正常）"
fi

echo
echo "日志中的 error / unsupported："
if grep -inE "error|unsupported|fatal" "$LOG" | head -5 | grep -q .; then
  grep -inE "error|unsupported|fatal" "$LOG" | head -5 | sed 's/^/    /'
  echo "  注：ERR_NAME_NOT_RESOLVED 通常来自构建时写入的占位更新源，属预期。"
else
  echo "    （无）"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "✓ 进程级验证通过。但窗口画面未能验证 —— Wayland 下无法截图，请人工确认界面。"
else
  echo "✗ 验证未通过，见上方 ✗ 项。完整日志：$LOG"
  exit 1
fi
echo "停止实例：pgrep -f 'mount_Deep[S]' | xargs -r kill"
