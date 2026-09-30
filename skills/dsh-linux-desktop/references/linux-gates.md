# DeepSeek Harness 桌面端在 Linux 上的六道闸门

本文记录 2026-09-30 在官方 tag `dsh-v0.2.0-rc.2`（commit `639ed01539`）上实测到的
阻断点。每道闸门都给出代码位置、失败信息和我采取的最小修复。

写这份文档的目的不是存档，而是让人在官方代码变动后能**重新推导**，而不是从零踩一遍。

## 目录

- [结论先行](#结论先行)
- [最具误导性的一处](#最具误导性的一处)
- [G1 目标白名单](#g1-目标白名单)
- [G2 更新目标白名单](#g2-更新目标白名单)
- [G3 二元 mac/win 回退](#g3-二元-macwin-回退)
- [G4 类型收窄导致 tsc 失败](#g4-类型收窄导致-tsc-失败)
- [G5 强制更新策略](#g5-强制更新策略)
- [G6 AppImage 可执行文件名](#g6-appimage-可执行文件名)
- [复现闸门仍在的检查命令](#复现闸门仍在的检查命令)
- [Linux 原生能力实测结果](#linux-原生能力实测结果)
- [未解决的限制](#未解决的限制)

---

## 结论先行

**官方桌面端在 Linux 上是零支持**，不是"缺少预编译包"，而是代码层面主动拒绝。
一共三道白名单/门禁挡在所有官方入口前（`package-target.ts`、`prepare-runtime.ts`、
`dev.ts` 共用 G1），另有三处在更深处才暴露。

官方分发渠道同样印证：`https://www.deepseek.com/harness` 页面只提供
`dsh-latest-macos-arm64.dmg` 和 `dsh-latest-windows-x64.exe` 两个文件，全页无
"linux" 字样。GitHub 上所有 Release 的 `assets` 均为空数组，从未发布过任何预编译二进制。

因此在 Linux 上获取桌面应用只有三条路：自建、装第三方社区包、或用 Web 版。

---

## 最具误导性的一处

`apps/desktop/scripts/electron-builder-config.mjs` 里确实存在：

```js
linux: {
  category: 'Development',
  target: ['AppImage'],
},
```

**这是死配置。** 任何官方入口都走不到它 —— `package-target.ts` 的目标联合类型是
`'mac-arm64' | 'mac-x64' | 'win-x64'`，在解析阶段就抛错；`dev.ts` 同样调用
`resolveDesktopBuildTarget()`。

这处配置大概是 electron-builder 的通用模板残留，DeepSeek 自己从未验证过。
下次如果有人在 Linux 上按官方文档尝试构建，先看到这行会误以为官方支持 Linux。

---

## G1 目标白名单

**位置**：`apps/desktop/scripts/desktop-build-paths.mjs:7`

```js
const SUPPORTED_TARGETS = new Set(['mac-arm64', 'mac-x64', 'win-x64'])
```

**失败信息**：

```
$ pnpm run package:desktop
Error: desktop package: unsupported build host linux-x64
    at hostTargetName (package-target.ts)

$ pnpm run prepare:runtime
Error: desktop build paths: unsupported target linux-x64
    at resolveDesktopBuildTarget (desktop-build-paths.mjs)
```

**影响面最广**：`package-target.ts`（打包）、`prepare-runtime.ts`（运行时准备）、
`prepare-package-set.ts`（包集合）、`dev.ts`（开发启动）全部经由
`resolveDesktopBuildTarget()`，一道白名单挡住全部入口。

**附带问题** —— 同文件 `desktopTargetPlatform()` 用二元回退推导平台：

```js
platform: target === 'win-x64' ? 'win32' : 'darwin'   // linux-x64 会落到 darwin
```

**修复**：白名单加 `'linux-x64'`，平台推导补一个分支。

---

## G2 更新目标白名单

**位置**：`apps/desktop/scripts/desktop-auto-update-environment.mjs:25`

```js
const UPDATE_TARGETS = new Set(['mac-arm64', 'mac-x64', 'win-x64'])
```

**失败信息**：

```
Error: desktop auto-update: unsupported target linux-x64
    at resolveDesktopAutoUpdateTarget
```

**何时触发**：绕过 G1 之后调 electron-builder 时。配置工厂的第 93 行无条件调用
`resolveDesktopAutoUpdateConfig()`（除非 unsigned，而 unsigned 在 Linux 上又被
另一条守卫禁止，见下）。

**注意这条相邻的守卫**：

```js
// electron-builder-config.mjs:62
if (unsigned && resolvedPlatform !== 'win32') throw new Error('desktop package: unsigned builds require Windows')
```

所以 Linux 上**不能**用 `DSH_DESKTOP_UNSIGNED=1` 绕过更新配置，必须提供更新源变量。

**修复**：白名单加 `'linux-x64'`。

---

## G3 二元 mac/win 回退

这是最隐蔽的一类：语法完全合法，只是把 linux 静默归类成了 Windows。

**位置一**：`apps/desktop/scripts/prepare-runtime.ts:34`

```js
const platform = target.startsWith('mac-') ? 'darwin' : 'win32'
```

`linux-x64` 不以 `mac-` 开头 → `platform = 'win32'` → 下载 **Windows 版** Electron。
白名单放开后不报错，只是拿错了东西。

**位置二**：`apps/desktop/scripts/prepare-runtime.ts:42`

```js
const executable = join(BUILD_PATHS.electron, platform === 'win32' ? 'electron.exe' : 'Electron.app/Contents/MacOS/Electron')
```

即使 platform 修对了，这里仍只有 mac 和 win 两种布局。Linux 的 Electron 发行版
可执行文件就叫 `electron`，既没有 `.exe` 后缀也没有 `.app` 包装。

**失败信息**（platform 还没修时）：

```
/path/to/electron.exe: 2: Syntax error: Unterminated quoted string
Error: Command failed: .../electron.exe -p process.versions.node
```

即把 Windows PE 文件当 shell 脚本执行。

**位置三**：`apps/desktop/scripts/prepare-dsh.ts:44` —— 同一处硬编码的第二个副本。
只改前一处会在 `prepare:dsh` 阶段以相同方式失败。

**修复**：三处都补 linux 分支。

---

## G4 类型收窄导致 tsc 失败

**位置**：`apps/desktop/scripts/prepare-cli.ts:11`

```ts
export function prepareDesktopCli(destination: string, platform: 'darwin' | 'win32'): void
```

G3 把 `platform` 放宽成三值后，这个签名接不住了：

```
apps/desktop/scripts/prepare-runtime.ts(59,62): error TS2345:
  Argument of type '"darwin" | "linux" | "win32"' is not assignable to
  parameter of type '"darwin" | "win32"'.
```

**还有一个语义问题**，类型报错掩盖了它：

```ts
if (platform === 'darwin') chmodSync(command, 0o755)   // Linux 同样需要可执行位
```

**修复**：类型放宽，`chmod` 条件从 `=== 'darwin'` 改为 `!== 'win32'`。

---

## G5 强制更新策略

这是唯一一处**应用运行时**的门禁，也是唯一一处我刻意没有改应用代码的地方。

**运行时门禁**：`apps/desktop/src/main.ts:1297`

```ts
if (!['win32', 'darwin'].includes(process.platform) || !['x64', 'arm64'].includes(process.arch))
  throw new Error('desktop policy: unsupported platform')
```

**失败信息**（AppImage 已构建、Electron 进程已起，但主进程拒绝）：

```
Error: desktop policy: unsupported platform
    at main (resources/app.asar/lib/main.js)
```

**为什么绕开它而不是改**：`src/mandatory-update-policy.ts` 的 `platform` 字段还要传给
`platformClientHeaders()`，那在共享包 `packages/credentials/deepseek-account` 里，
改它会牵连到账户功能。而且这块逻辑是 DeepSeek 用于强制用户更新的分发策略，
个人自建包本就不该携带。

**实际做法** —— 让 manifest 里没有这个键，`main.ts` 就整段跳过：

```ts
// main.ts:1288 —— 键不存在时 policyInput 为 undefined
? ('dshMandatoryUpdatePolicy' in manifest ? manifest.dshMandatoryUpdatePolicy : undefined)

// mandatory-update-policy.ts:56
export function resolveDesktopPolicyConfig(input: unknown, ...): DesktopPolicyConfig | undefined {
  if (input === undefined) return undefined      // ← 整段策略代码跳过
```

配套改 `electron-builder-config.mjs`，仅在真的配置了策略源时才解析并写入：

```js
const policyConfigured = env.DSH_DESKTOP_MANDATORY_UPDATE_TEST_ORIGIN !== undefined
  || env.DSH_DESKTOP_MANDATORY_UPDATE_PROD_ORIGIN !== undefined
const policy = policyConfigured ? resolveDesktopPolicyEnvironment(env) : undefined
// ...
...policy === undefined ? {} : { dshMandatoryUpdatePolicy: policy },
```

`apps/desktop/src/` 因此保持零改动。

---

## G6 AppImage 可执行文件名

**位置**：`apps/desktop/scripts/electron-builder-config.mjs` 的 `linux` 块

**失败信息**（此时 `linux-unpacked` 已成功产出，只差最后封装）：

```
⨯ failed to build AppImage  error=executableName contains characters that cannot be
   safely used in file paths: @deepseek-aidsh-desktop.
   Please use only letters, digits, hyphens, underscores, dots, and spaces.
```

npm 包名 `@deepseek-ai/dsh-desktop` 被拼成 `@deepseek-aidsh-desktop`，含 `@` 和 `/`。
AppImage 的 AppDir 内部路径不能含这些字符；macOS 的 dmg 和 Windows 的 nsis 没有这个
限制，所以官方从未触发。

**修复**：显式指定 `executableName: 'deepseek-harness'`。顺带补 `.desktop` 条目的
显示名，否则应用菜单里会显示可执行文件名。

---

## 复现闸门仍在的检查命令

官方代码更新后，用这几条快速判断哪些闸门还在、哪些已经不需要打了：

```bash
REPO=/home/lin/deepseek-harness

# G1 目标白名单
grep -n "SUPPORTED_TARGETS = " $REPO/apps/desktop/scripts/desktop-build-paths.mjs

# G2 更新目标白名单
grep -n "UPDATE_TARGETS = " $REPO/apps/desktop/scripts/desktop-auto-update-environment.mjs

# G3 三处二元回退
grep -rn "startsWith('mac-') ? 'darwin' : 'win32'" $REPO/apps/desktop/scripts/
grep -rn "Electron.app/Contents/MacOS/Electron" $REPO/apps/desktop/scripts/

# G4 类型签名与 chmod
grep -n "platform: 'darwin' | 'win32'" $REPO/apps/desktop/scripts/prepare-cli.ts
grep -n "chmodSync" $REPO/apps/desktop/scripts/prepare-cli.ts

# G5 运行时门禁与 manifest 键
grep -n "unsupported platform" $REPO/apps/desktop/src/main.ts
grep -n "dshMandatoryUpdatePolicy" $REPO/apps/desktop/scripts/electron-builder-config.mjs

# G6 linux 块是否已带 executableName
grep -n -A6 "^    linux: {" $REPO/apps/desktop/scripts/electron-builder-config.mjs

# 官方目标联合类型（判断官方是否已自行支持 Linux）
grep -n "DesktopPackageTargetName =" $REPO/apps/desktop/scripts/package-target.ts
```

`patch-linux-target.mjs` 在锚点缺失时会打印实际附近内容并以非零码退出，
所以直接跑它比逐条 grep 更省事。

---

## Linux 原生能力实测结果

`prepare:dsh` 阶段自带冒烟测试，在 Linux x64 上全部通过：

```json
{"node":"24.18.1","platform":"linux","arch":"x64","koffi":true,
 "sharp":true,"html":true,"pty":true,"pnpm":true,"grep":true,"glob":true}
```

- `koffi` — FFI，沙箱与原生调用依赖
- `sharp` — 图像处理
- `pty` — 终端功能（node-pty 有 Linux 预编译包）
- `html` — Office/PDF 文档转换
- `grep` / `glob` — 工具链

同时通过：`DOCX, XLSX, PPTX to PDF and skill CLI discovery passed`。
该步骤还会真实启动 Host 并打印带 token 的 Web UI 地址。

运行期观察到的进程树（功能完整的标志）：

```
main → zygote → gpu-process(--ozone-platform=wayland, /dev/dri/render 硬件加速)
                → renderer                                  ← 窗口已创建并渲染
                → 内嵌 dsh 运行时子进程
```

**这说明应用运行时代码本身对 Linux 的支持是完整的**，卡住的从来只是构建与分发层。
唯一需要改的运行时代码是 G5 的策略门禁，而那是被有意绕开的。

---

## 未解决的限制

诚实记录，避免下次误判：

1. **窗口画面未经视觉验证。** Wayland 会话下窗口不是 X11 窗口，
   `xdotool` / `wmctrl` / `import` 都看不到，只能靠 renderer 进程存在来间接推断。
2. **AppImage 未签名。** Linux 桌面常态，但系统不会给它任何信任保证。
3. **更新源是占位域名** `https://updates.invalid`，永远不会自动更新，也不连
   DeepSeek 的真实更新基础设施。要更新只能手动替换文件。
4. **系统托盘未验证。** 官方文档明确托盘图标是 Windows 专属，macOS 不提供；
   Linux 的行为没有官方说明。
5. **G5 的绕法是构建期规避，不是平台支持。** 如果将来需要让 Linux 版携带
   真正的强制更新策略，仍要回去改 `main.ts:1297` 和 `platformClientHeaders()`。
