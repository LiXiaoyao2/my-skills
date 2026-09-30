#!/usr/bin/env node
/**
 * Add Linux x64 support to the DeepSeek Harness Desktop build pipeline.
 *
 * Every edit is anchored to exact upstream text. That anchoring is deliberate:
 * upstream ships no Linux target, so these lines are the only thing standing
 * between us and a silent no-op. If an anchor is missing the script prints the
 * surrounding context and exits non-zero, because a build that quietly skipped
 * a gate would fail much later with a baffling "unsupported target linux-x64"
 * and no hint that the patch was incomplete.
 *
 * Re-running is safe: an edit already applied is reported as such and skipped.
 *
 * Usage: node patch-linux-target.mjs <path-to-deepseek-harness>
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

/** @typedef {{ file: string, gate: string, from: string, to: string }} Edit */

/** @type {Edit[]} */
const EDITS = [
  {
    file: 'apps/desktop/scripts/desktop-build-paths.mjs',
    gate: 'G1 目标白名单：打包/准备/dev 共用的唯一入口',
    from: "const SUPPORTED_TARGETS = new Set(['mac-arm64', 'mac-x64', 'win-x64'])",
    to: "const SUPPORTED_TARGETS = new Set(['mac-arm64', 'mac-x64', 'win-x64', 'linux-x64'])",
  },
  {
    file: 'apps/desktop/scripts/desktop-build-paths.mjs',
    gate: 'G1 平台推导：二元回退会把 linux 误判成 win32',
    from: "    platform: /** @type {'darwin' | 'win32'} */ (target === 'win-x64' ? 'win32' : 'darwin'),",
    to: "    platform: /** @type {'darwin' | 'win32' | 'linux'} */ (target === 'win-x64' ? 'win32' : target === 'linux-x64' ? 'linux' : 'darwin'),",
  },
  {
    file: 'apps/desktop/scripts/desktop-auto-update-environment.mjs',
    gate: 'G2 更新目标白名单：打包时解析更新源会撞上它',
    from: "const UPDATE_TARGETS = new Set(['mac-arm64', 'mac-x64', 'win-x64'])",
    to: "const UPDATE_TARGETS = new Set(['mac-arm64', 'mac-x64', 'win-x64', 'linux-x64'])",
  },
  {
    file: 'apps/desktop/scripts/prepare-runtime.ts',
    gate: 'G3 平台推导：非 mac- 一律当 win32，会下载 Windows 版 Electron',
    from: "  const platform = target.startsWith('mac-') ? 'darwin' : 'win32'",
    to: "  const platform = target.startsWith('mac-') ? 'darwin' : target.startsWith('linux-') ? 'linux' : 'win32'",
  },
  {
    file: 'apps/desktop/scripts/prepare-runtime.ts',
    gate: 'G3 Electron 可执行文件：Linux 下没有 .exe 也没有 Electron.app',
    from: "  const executable = join(BUILD_PATHS.electron, platform === 'win32' ? 'electron.exe' : 'Electron.app/Contents/MacOS/Electron')",
    to: "  const executable = join(BUILD_PATHS.electron, platform === 'win32' ? 'electron.exe' : platform === 'darwin' ? 'Electron.app/Contents/MacOS/Electron' : 'electron')",
  },
  {
    file: 'apps/desktop/scripts/prepare-dsh.ts',
    gate: 'G3 同一处硬编码的第二个副本',
    from: "const NODE = join(BUILD_PATHS.electron, process.platform === 'win32' ? 'electron.exe' : 'Electron.app/Contents/MacOS/Electron')",
    to: "const NODE = join(BUILD_PATHS.electron, process.platform === 'win32' ? 'electron.exe' : process.platform === 'darwin' ? 'Electron.app/Contents/MacOS/Electron' : 'electron')",
  },
  {
    file: 'apps/desktop/scripts/prepare-cli.ts',
    gate: 'G4 CLI 落地脚本：类型需接受 linux，否则 tsc 直接失败',
    from: "export function prepareDesktopCli(destination: string, platform: 'darwin' | 'win32'): void {",
    to: "export function prepareDesktopCli(destination: string, platform: 'darwin' | 'linux' | 'win32'): void {",
  },
  {
    file: 'apps/desktop/scripts/prepare-cli.ts',
    gate: 'G4 可执行位：原来只给 darwin 加 chmod，Linux 同样需要',
    from: "  if (platform === 'darwin') chmodSync(command, 0o755)",
    to: "  if (platform !== 'win32') chmodSync(command, 0o755)",
  },
  {
    file: 'apps/desktop/scripts/electron-builder-config.mjs',
    gate: 'G5 强制更新策略：仅在真的配置了策略源时才解析',
    from: '  const policy = resolveDesktopPolicyEnvironment(env)',
    to: "  const policyConfigured = env.DSH_DESKTOP_MANDATORY_UPDATE_TEST_ORIGIN !== undefined\n    || env.DSH_DESKTOP_MANDATORY_UPDATE_PROD_ORIGIN !== undefined\n  const policy = policyConfigured ? resolveDesktopPolicyEnvironment(env) : undefined",
  },
  {
    file: 'apps/desktop/scripts/electron-builder-config.mjs',
    gate: 'G5 策略不写入 manifest，main.ts 就会整段跳过该策略',
    from: '      dshMandatoryUpdatePolicy: policy,',
    to: '      ...policy === undefined ? {} : { dshMandatoryUpdatePolicy: policy },',
  },
  {
    file: 'apps/desktop/scripts/electron-builder-config.mjs',
    gate: 'G6 AppImage 要求可执行文件名不含 @ 和 /，npm 包名不满足',
    from: "    linux: {\n      category: 'Development',\n      target: ['AppImage'],\n    },",
    to: "    linux: {\n      category: 'Development',\n      target: ['AppImage'],\n      // AppImage requires a filesystem-safe executable name; the npm package name (@deepseek-ai/dsh-desktop) is not one.\n      executableName: 'deepseek-harness',\n      desktop: { entry: { Name: 'DeepSeek Harness' } },\n    },",
  },
]

const repo = process.argv[2]
if (repo === undefined) {
  console.error('usage: node patch-linux-target.mjs <path-to-deepseek-harness>')
  process.exit(2)
}

const cache = new Map()
/** @param {string} rel */
const read = rel => {
  if (!cache.has(rel)) cache.set(rel, readFileSync(join(repo, rel), 'utf8'))
  return cache.get(rel)
}

let applied = 0
let already = 0
/** @type {{ gate: string, file: string, from: string }[]} */
const failed = []

for (const edit of EDITS) {
  const text = read(edit.file)
  if (text.includes(edit.to)) {
    console.log(`  = 已应用  ${edit.gate}`)
    already += 1
    continue
  }
  if (!text.includes(edit.from)) {
    failed.push(edit)
    continue
  }
  cache.set(edit.file, text.replace(edit.from, edit.to))
  console.log(`  + 已修补  ${edit.gate}`)
  applied += 1
}

for (const [rel, text] of cache) {
  const abs = join(repo, rel)
  const current = readFileSync(abs, 'utf8')
  if (current !== text) writeFileSync(abs, text)
}

/**
 * Print the region of a file most likely to hold a failed anchor.
 *
 * Matching on the whole anchor is useless once upstream rewrites the line, so
 * fall back to the longest identifier in it (SUPPORTED_TARGETS, NODE,
 * prepareDesktopCli, …). That identifier usually survives a refactor even when
 * the surrounding expression does not, which is exactly the line someone needs
 * to look at to re-derive the edit.
 * @param {string} text - Full file contents.
 * @param {string} anchor - The anchor text that was not found.
 */
function showContext(text, anchor) {
  const lines = text.split('\n')
  const identifiers = [...new Set(anchor.match(/[A-Za-z_$][A-Za-z0-9_$]{5,}/g) ?? [])]
    .sort((a, b) => b.length - a.length)
  let at = -1
  for (const id of identifiers) {
    at = lines.findIndex(line => line.includes(id))
    if (at >= 0) break
  }
  if (at < 0) {
    console.error('  实际内容里找不到该锚点的任何标识符，文件开头如下：')
    for (const [i, line] of lines.slice(0, 6).entries()) console.error(`    ${i + 1} | ${line}`)
    return
  }
  console.error(`  实际内容（第 ${at + 1} 行附近，含标识符 ${identifiers.find(id => lines[at].includes(id))}）：`)
  const start = Math.max(0, at - 2)
  for (const [i, line] of lines.slice(start, start + 7).entries()) {
    console.error(`    ${start + i + 1} | ${line}`)
  }
}

if (failed.length > 0) {
  console.error(`\n✗ ${failed.length} 处锚点未找到 —— 上游代码已变动，需要人工重新分析：\n`)
  for (const edit of failed) {
    console.error(`  闸门: ${edit.gate}`)
    console.error(`  文件: ${edit.file}`)
    console.error(`  期望包含: ${edit.from.split('\n')[0]}`)
    showContext(read(edit.file), edit.from)
    console.error('')
  }
  console.error('参考 references/linux-gates.md 重新推导这些改动。')
  process.exit(1)
}

console.log(`\n✓ 补丁完成：本次修补 ${applied} 处，已存在 ${already} 处，合计 ${EDITS.length} 处闸门。`)
console.log('  应用运行时代码（apps/desktop/src/）未被改动。')
console.log(`  查看改动: cd ${repo} && git diff`)
