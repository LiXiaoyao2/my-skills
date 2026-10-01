# my-skills

个人技能仓库。技能放在 `skills/` 子目录下，每个技能一个独立目录，内含 `SKILL.md`，
可被 cc-switch 直接识别并安装到 Claude Code / minimax Code / Codex 的技能目录。

私有仓库，不对外公开。

## 结构

```
my-skills/
├── README.md
└── skills/                   ← 必须存在，cc-switch 按此目录发现技能
    └── <技能名>/
        ├── SKILL.md          必需：YAML frontmatter + 技能说明
        ├── scripts/          可选：可执行脚本
        ├── references/       可选：按需加载的参考文档
        └── assets/           可选：输出用模板/资源
```

> ⚠️ **`skills/` 这一层不能省。** 技能目录必须放在 `skills/` 下，不能直接放在仓库根目录。
> 少了这层，cc-switch 扫描时会报 `SKILL_DIR_NOT_FOUND`，技能列表里一个都看不到。
> 对照 `obra/superpowers`、`anthropics/skills`、`MiniMax-AI/skills`、
> `JimLiu/baoyu-skills` 这四个能被识别的仓库，顶层都是 `skills/`。

## 安装某个技能

在 cc-switch 里添加本仓库（`LiXiaoyao2/my-skills`）后，直接从界面安装即可。

手动安装则把技能目录软链到技能搜索路径（本机是 `~/.cc-switch/skills`，再由
`~/.claude/skills` 软链过去）：

```bash
ln -s "$PWD/skills/dsh-linux-desktop" ~/.cc-switch/skills/dsh-linux-desktop
ln -s ~/.cc-switch/skills/dsh-linux-desktop ~/.claude/skills/dsh-linux-desktop
```

或直接复制：

```bash
cp -r skills/dsh-linux-desktop ~/.claude/skills/
```

## 卸载

```bash
rm ~/.claude/skills/dsh-linux-desktop ~/.cc-switch/skills/dsh-linux-desktop
```

## 新增技能

1. 建 `skills/<技能名>/SKILL.md`，frontmatter 至少含 `name` 和 `description`
2. `description` 决定触发准确率，写清「做什么」和「什么情况下用」
3. 提交推送：`git add . && git commit -m "..." && git push`
4. 在 cc-switch 里刷新本仓库，新技能即可被发现

## 现有技能

| 技能 | 说明 |
|---|---|
| [dsh-linux-desktop](skills/dsh-linux-desktop/) | 从官方源码构建 DeepSeek Harness 桌面端的 Linux x64 AppImage。官方不发布 Linux 包且构建流水线硬编码拒绝 Linux，需要打 11 处锚点补丁。 |
| [dsh-web-service](skills/dsh-web-service/) | 把 dsh 的 web 版注册成 systemd 用户服务常驻。解决 token 认证（裸地址必 401）、端口冲突、启动 URL 丢失三个痛点；也用于判断该不该常驻，以及怎么拆掉回归手动 `dsh web`。 |

本仓库只放**通用技能**。领域专用、内容敏感或需要独立版本历史的技能，放在各自专属的
私有仓库维护，不并入这里（例如小鹅通课程归档工具，仓库地址 `LiXiaoyao2/xiaoe-course-archiver`，
其技能位于该仓库的 `skill/` 目录）。

## 约定

- 技能里不要写死绝对路径，用 `~` 或相对自身目录的路径
- 脚本要可重复运行（幂等），失败时明确报错而非静默跳过
- 改动应用源码时，尽量把修改收敛在构建/配置层，并保持应用逻辑零改动

## 来源与许可

本仓库为个人技术笔记与工具集合。

- `skills/dsh-linux-desktop/` 中的分析与补丁针对
  [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)
  （**MIT License**，Copyright DeepSeek）。该技能不包含其源码分发，仅含分析文档、
  以及在构建时对其脚本做定点替换的补丁脚本。引用代码片段用于说明问题，符合 MIT 条款。
- `skills/dsh-web-service/` 记录的是同一个上游的 web 版行为（认证流程、cookie
  结构、配置面），同样只含实测结论与自建脚本，不分发其源码。

## 在 cc-switch 中使用

添加技能仓库时填 `LiXiaoyao2/my-skills`。

> ⚠️ 该功能通过匿名方式下载 `https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip`，
> **只支持公开仓库**。私有仓库会返回 404（GitHub 用 404 而非 403 以避免泄露仓库存在性），
> 且 cc-switch 未提供配置 GitHub 凭据的入口 —— 二进制里的 `github_token` 属于
> Copilot OAuth，与技能下载无关。

