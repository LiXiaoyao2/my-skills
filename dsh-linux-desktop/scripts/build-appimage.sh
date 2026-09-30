#!/usr/bin/env bash
#
# Build a Linux x64 AppImage of DeepSeek Harness Desktop from official source.
#
# This replicates the packaging sequence in apps/desktop/scripts/package-target.ts,
# minus the macOS/Windows signing, notarization and upload stages. The sequence
# order matters and is not obvious from reading the scripts: release:pack must
# populate packed/dsh and packed/vendor BEFORE prepare:packages reads them, and
# prepare:runtime must run after native/system is built for the target.
#
# Phases (run separately so a late failure doesn't cost a 20-minute rebuild):
#   prep      8 preparation steps, produces the dsh runtime tree
#   package   electron-builder, produces the AppImage
#   all       both (default)
#
# Usage: build-appimage.sh [all|prep|package] [--repo PATH] [--out PATH]

set -euo pipefail

PHASE="all"
REPO="${DSH_REPO:-/home/lin/deepseek-harness}"
OUT=""

while [ $# -gt 0 ]; do
  case "$1" in
    all|prep|package) PHASE="$1" ;;
    --repo) REPO="$2"; shift ;;
    --out)  OUT="$2";  shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
  shift
done

APPS="$REPO/apps/desktop"
TARGET="linux-x64"
PACKED="$APPS/.desktop-build/targets/$TARGET/packed"
ARTIFACTS="$APPS/.desktop-build/targets/$TARGET/artifacts"
[ -n "$OUT" ] || OUT="/home/lin/DeepSeek-Harness-$(node -p "require('$APPS/package.json').version" 2>/dev/null || echo dev)-linux-x86_64.AppImage"

# The build refuses to run unsigned on anything but Windows
# (electron-builder-config.mjs: "unsigned builds require Windows"), so a
# self-built AppImage always carries update metadata. Point it at a
# deliberately unresolvable origin: this build is not signed and not published,
# so there is nothing to update from, and reaching DeepSeek's real feed would
# only ever produce a lookup miss.
export DSH_DESKTOP_TARGET_PLATFORM=linux
export DSH_DESKTOP_TARGET_ARCH=x64
export DSH_DESKTOP_APP_ID=com.deepseek.harness
export DSH_DESKTOP_AUTO_UPDATE_ENV=test
export DOWNLOAD_TEST_ORIGIN=https://updates.invalid
export DOWNLOAD_TEST_RELEASE_ID="${DOWNLOAD_TEST_RELEASE_ID:-$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')}"

step() { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ -d "$REPO/.git" ] || die "不是 git 仓库: $REPO （先克隆 https://github.com/deepseek-ai/deepseek-harness）"
[ -f "$APPS/package.json" ] || die "缺少 $APPS/package.json"

prep() {
  cd "$REPO" || die "无法进入 $REPO"

  step "0/8 启用仓库锁定的 pnpm"
  # The repo pins pnpm via packageManager; the system pnpm may be a different
  # major and will reject the lockfile.
  corepack enable
  corepack prepare "$(node -p "require('$REPO/package.json').packageManager")" --activate >/dev/null
  echo "pnpm $(pnpm -v)  node $(node -v)"

  step "1/8 build:official"
  pnpm run build:official

  step "2/8 release:pack dsh"
  pnpm run release:pack --family dsh --out "$PACKED/dsh"

  step "3/8 pack desktop-host"
  pnpm --dir apps/desktop-host pack --pack-destination "$PACKED/dsh"

  step "4/8 release:pack vendor"
  pnpm run release:pack --family vendor --out "$PACKED/vendor"

  step "5/8 native/system build:ts"
  rm -rf "$PACKED/landlock"; mkdir -p "$PACKED/landlock"
  pnpm --dir native/system run build:ts

  step "6/8 pack native/system entry"
  pnpm --dir native/system/packages/entry pack --pack-destination "$PACKED/landlock"

  step "7/8 prepare:packages"
  ( cd "$APPS" && pnpm run prepare:packages )

  step "8/8 prepare:dsh"
  # This step smoke-tests the real runtime: it boots the Host, converts a
  # document to PDF and resolves the skill CLI. A failure here means the
  # AppImage would be broken, so don't skip it.
  ( cd "$APPS" && pnpm run prepare:dsh )

  echo
  echo "准备阶段完成。产物："
  ls -1 "$PACKED"
}

package() {
  [ -d "$PACKED/dsh" ] || die "缺少 $PACKED/dsh —— 先跑 prep 阶段"
  step "electron-builder"
  ( cd "$APPS" && pnpm exec electron-builder \
      --config electron-builder.config.mjs \
      --linux AppImage --x64 --publish never )

  local built
  built="$(ls -t "$ARTIFACTS"/*.AppImage 2>/dev/null | head -1 || true)"
  [ -n "$built" ] || die "artifacts 目录下没有 .AppImage"
  cp "$built" "$OUT"
  chmod +x "$OUT"
  echo
  echo "✓ $OUT"
  ls -la "$OUT"
}

case "$PHASE" in
  prep)    prep ;;
  package) package ;;
  all)     prep; package ;;
esac
