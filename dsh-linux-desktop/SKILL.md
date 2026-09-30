---
name: dsh-linux-desktop
description: 从官方源码构建 DeepSeek Harness 桌面端的 Linux x64 AppImage。官方不发布任何 Linux 预编译包，且其构建流水线在代码层面硬编码拒绝 Linux，需要打一组锚点式补丁才能产出可运行的桌面应用。只要用户提到 dsh 桌面版、DeepSeek Harness 桌面端、dsh desktop、AppImage、或者想在 Linux（Ubuntu/Debian/Fedora/Arch）上得到 Harness 的原生桌面窗口，就使用本技能——包括"再构建一次""重新构建""换个版本构建""上次那个 AppImage 怎么来的"这类追问。本技能也用于判断官方是否已支持 Linux、以及遇到 unsupported target linux-x64、unsupported build host、desktop policy 报 unsupported platform 这类报错时的排查。
---

# 构建 DeepSeek Harness 桌面端 Linux 版

## 你要先知道的事

**DeepSeek 官方在 Linux 上不提供桌面版，也不会发布。** 这不是"暂时没出 Linux 包"，
而是构建流水线在代码层面主动拒绝 Linux。

官方分发页 `https://www.deepseek.com/harness` 只提供两个文件：
`dsh-latest-macos-arm64.dmg` 和 `dsh-latest-windows-x64.exe`，全页无 "linux" 字样。
GitHub 上所有 Release 的 `assets` 都是空数组。

如果用户以为"换个下载源"就能解决，直接告诉他结论，别让他在搜索里浪费时间。

在 Linux 上想要原生窗口，只有三条路：

| 路线 | 代价 |
|---|---|
| **自建（本技能）** | 首次约 25 分钟，磁盘约 15GB；之后可重复构建 |
| 第三方社区包 | 快，但未签名、与官方无隶属关系、锁在旧版上游 |
| Web 版 | 零成本，但只有浏览器标签页 |

**应用运行时代码本身对 Linux 的支持是完整的** —— 沙箱 FFI、图像处理、终端、
Office/PDF 转换、grep/glob 全部实测通过，卡住的只是构建与分发层。所以自建这条路
是走得通的，不需要魔改应用逻辑。

## 最短路径

```bash
S=~/.cc-switch/skills/dsh-linux-desktop/scripts

# 1. 克隆并锁定到已验证的 tag
git clone https://github.com/deepseek-ai/deepseek-harness.git
cd deepseek-harness && git checkout dsh-v0.2.0-rc.2

# 2. 打补丁（幂等，可重复运行）
node $S/patch-linux-target.mjs "$PWD"

# 3. 准备 + 打包
bash $S/build-appimage.sh all --repo "$PWD"

# 4. 验证能启动
bash $S/verify-appimage.sh ~/DeepSeek-Harness-0.2.0-rc.2-linux-x86_64.AppImage
```

产物默认落在 `/home/lin/DeepSeek-Harness-<版本>-linux-x86_64.AppImage`（约 355MB）。

## 锁 tag 还是跟最新版

默认锁 `dsh-v0.2.0-rc.2` —— 这个版本本技能完整验证过，可复现。

想用仓库最新版（拿到官方新特性）：

```bash
git fetch && git checkout master
node $S/patch-linux-target.mjs "$PWD"   # 锚点对不上会明确报错
```

`patch-linux-target.mjs` 在任何锚点找不到时会打印该文件实际的相关内容并以非零码退出。
这是刻意的：官方若重构了那几行，静默跳过会让构建在更晚的地方以
"unsupported target linux-x64" 失败，而没有任何提示说明补丁没打全。

**遇到锚点失败时**，读 `references/linux-gates.md` 重新推导那一处 —— 文档里记了
每道闸门的代码位置、失败信息、修复原因。重新推导后把它加进脚本的 `EDITS` 数组。

## 构建为什么要分阶段

`build-appimage.sh` 支持 `prep` / `package` / `all` 三个阶段。默认 `all`，
但值得知道为什么能拆开 —— 准备阶段要跑 20 多分钟，而 electron-builder 偶尔会因为
环境变量问题失败。分阶段可以只重跑最后一步：

```bash
bash $S/build-appimage.sh prep    --repo "$PWD"   # 8 步准备
bash $S/build-appimage.sh package --repo "$PWD"   # 只跑 electron-builder
```

**步骤顺序不能随意调整**，这点从脚本里读不出来：

```
1 build:official          ← 会重新编译 native/system，必须最先
2 release:pack dsh        ← 产出 packed/dsh
3 pack desktop-host       ← 追加进 packed/dsh
4 release:pack vendor     ← 产出 packed/vendor
5 native/system build:ts  ← 清理并重建 packed/landlock
6 pack native/system entry
7 prepare:packages        ← 读 packed/dsh，所以必须在 2/3 之后
8 prepare:dsh             ← 自带冒烟测试：真启 Host、转 PDF、找 skill CLI
```

第 8 步失败就意味着产出的 AppImage 是坏的，别跳过它只看退出码。

## 补丁改了什么

11 处编辑，跨 6 个文件，**全部在 `apps/desktop/scripts/`（构建脚本），
`apps/desktop/src/`（应用运行时代码）零改动**。

三类改动：

1. **放开三道目标白名单** —— `SUPPORTED_TARGETS`、`UPDATE_TARGETS`、以及
   `dev.ts` 共用的入口。官方只认 mac/win。
2. **补平台分支** —— 官方多处是 `startsWith('mac-') ? 'darwin' : 'win32'` 这种二元回退，
   linux 会被静默归类成 Windows（最隐蔽的一类：不报错，只是拿错东西）。
3. **两处平台特有问题** —— AppImage 要求可执行文件名不含 `@` 和 `/`；
   强制更新策略的运行时门禁只允许 win32/darwin。

第三类里的策略问题值得单独说：我是让构建配置在**未设置策略源时不把
`dshMandatoryUpdatePolicy` 写进 manifest**，于是 `main.ts` 整段策略逻辑自动跳过，
而不是去改 `main.ts:1297` 的平台判断。理由是那块代码是 DeepSeek 的强制更新分发
策略，个人自建包本就不该携带；改它还要牵连共享包里的 `platformClientHeaders()`。

完整分析见 `references/linux-gates.md`。

## 构建期环境变量

脚本已设好，通常不用管，但知道它们是什么有助于排障：

| 变量 | 值 | 为什么 |
|---|---|---|
| `DSH_DESKTOP_TARGET_PLATFORM` / `_ARCH` | `linux` / `x64` | 选择构建目标 |
| `DSH_DESKTOP_APP_ID` | `com.deepseek.harness` | 官方 app id，必填 |
| `DSH_DESKTOP_AUTO_UPDATE_ENV` | `test` | 发布环境标记 |
| `DOWNLOAD_TEST_ORIGIN` | `https://updates.invalid` | 见下 |
| `DOWNLOAD_TEST_RELEASE_ID` | 随机 32 位十六进制 | 更新批次 id |

**更新源为什么是占位域名**：Linux 上不能用 `DSH_DESKTOP_UNSIGNED=1` 绕过更新配置
（官方有守卫 `unsigned builds require Windows`），所以必须提供一个 HTTPS 源。
这个包没签名也没发布，本来就无更新可查；指向不可解析的域名可以避免去连 DeepSeek 的
真实更新基础设施。

运行期日志里那条 `net::ERR_NAME_NOT_RESOLVED` 就是它，属预期。

## 验证到什么程度算够

`verify-appimage.sh` 检查进程树（main / renderer / gpu / 内嵌 dsh 运行时）、
Host 端口 `19387` 是否响应、账号 API 是否连通。

**但它证明不了界面长什么样。** Wayland 会话下应用窗口不是 X11 窗口，
`xdotool` / `wmctrl` / `import` 都看不到，只能靠 renderer 进程存在间接推断窗口已创建。

所以验证完要如实告诉用户"进程级验证通过，界面需要你亲眼确认"，不要说成"已验证可用"。
这是 Linux 桌面环境验证的真实边界，夸大它会让用户误以为万事大吉。

## 别踩的坑

- **`pnpm install` 和构建命令必须在仓库目录执行。** 后台任务不继承你之前 `cd` 的目录，
  漏掉 `cd` 会得到 `ERR_PNPM_NO_PKG_MANIFEST: No package.json found in /home/lin`。
  把 `cd` 写进命令字符串里，别指望继承。

- **必须用 corepack 启用仓库锁定的 pnpm。** `package.json` 里
  `"packageManager": "pnpm@11.7.0"`，系统 pnpm 是 12.x，会拒绝 lockfile。

- **`pkill -f` / `pgrep -f` 会匹配到自己的命令行。** 停 AppImage 时用字符类：
  `pgrep -f "mount_Deep[S]"` 而不是 `pgrep -f "mount_DeepSeek"`。我在这上面自杀过两次。

- **磁盘要留够。** 依赖 1.9G，加上 node_modules、构建产物和 355MB 的 AppImage，
  整个流程约 15GB。

- **桌面端默认端口 19387，Web 版用 3080**，两者不冲突，可以同时跑。

## 已知未验证项

- 窗口画面（见上，Wayland 限制）
- 系统托盘：官方文档说托盘是 Windows 专属、macOS 不提供，Linux 行为无官方说明
- 自动更新：更新源是占位域名，永远不会触发
- G5 是构建期规避而非平台支持。若将来要在 Linux 上携带真正的强制更新策略，
  仍要回去改 `main.ts:1297` 和 `platformClientHeaders()`

## 参考

- `scripts/patch-linux-target.mjs` —— 11 处锚点式幂等补丁
- `scripts/build-appimage.sh` —— 分阶段构建
- `scripts/verify-appimage.sh` —— 启动验证
- `references/linux-gates.md` —— 六道闸门的代码级分析与复现命令
