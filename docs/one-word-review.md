# 说“复盘”，把项目经验提交回 PrizeOps

这是一项 **AI 助手 Skill + 确定性发布脚本**。Skill 整理当前对话与项目证据，脚本用已登录的 GitHub CLI 创建 Fork、分支和 PR。不是后台监听，也不能读取已经不可见的历史聊天。

## 一次安装

需要 Python 3.8+、Git、GitHub CLI，以及支持加载 Skill 的 Codex 或 Claude Code。

在 PrizeOps 仓库根目录运行：

```bash
gh auth login --hostname github.com
python -X utf8 07-crystal/install_review_skill.py --agent codex --enable-public-pr
```

Claude Code 将 `--agent codex` 换成 `--agent claude-code`。自定义 Skill 路径可用 `--destination` 指定完整目录。安装器不会覆盖已有目录或修改 Git 身份。

**`--enable-public-pr` 表示你同意：以后在项目中说“复盘”，助手可把整理后的报告公开提交到 `rfdiosuao/prize-ops`。** 不需要复制 Token，也不会把整个源项目推过去。如果不希望预先开启，去掉该参数，首次发布时再确认。请先确保你有权公开项目经验。

重新加载 AI 助手后，在想复盘的项目对话里说：

> 复盘

如果助手没有自动发现 Skill，可明确说“使用 prizeops-review 复盘当前项目”。仅克隆本仓库不代表 Skill 已安装；不同宿主的发现行为可能不同。

## 会发生什么

1. 识别当前 Git 项目，列出已跟踪 Markdown 候选和最近 60 条提交，不扫描其他项目。
2. AI 结合当前可见对话及相关文档，整理需求、调研、设计、开发、测试、部署、展示和经验；不明之处写未记录。
3. 报告保存在源项目 `.prizeops-review/report.md`，同次复盘 ID 存在同目录 `id.txt`。
4. AI 检查公开范围，脚本拦截常见密钥、个人路径、联系方式及嵌入图片/HTML。检测不是保密或事实正确性的保证；不适合公开的内容不发布。
5. 通过登录用户的 Fork 向上游提交一份 Markdown；没有上游写权限也可贡献，不改你的源码或分支。
6. 返回 PR 链接。同 ID 更新开放 PR；内容相同不增加提交。已经合并/关闭的 PR 不重开，下一轮用新 ID。

GitHub 账号不等于 CLI 已登录；网络、组织权限或 Fork 限制仍可能阻止提交。失败时报告保留本地，不谎报成功。新用户默认不会自动合并 PR。

提交前后会核对分支差异仅包含目标复盘文件。同名分支混有其他修改时停止，不强推或覆盖。首次 Fork 尚未完成初始化时可能需要稍后用同一 ID 重试。

## 本地模式与撤销

说“复盘，只保存在本地，不上传”。私有项目默认先本地，单独确认允许公开的摘要范围。

撤销自动发布，在**已安装 Skill** 的目录运行：

```bash
python -X utf8 scripts/review_flow.py consent --revoke
```

## 手动使用 / 排错

以下命令在 Skill 目录执行，参数填实际项目和报告路径：

```bash
python -X utf8 scripts/review_flow.py status
python -X utf8 scripts/review_flow.py collect --project /path/to/project
python -X utf8 scripts/review_flow.py publish --report /path/to/report.md --id my-project-2026 --dry-run
python -X utf8 scripts/review_flow.py publish --report /path/to/report.md --id my-project-2026 --allow-public-pr
```

`collect` 只提供本地证据目录，不调用模型；报告由当前助手生成。`publish` 只读指定报告，不打包源项目。`--allow-public-pr` 是本次发布许可，不更改持续授权。退出码：0 成功或 dry-run；2 缺公开许可；3 未登录；1 检查/网络/权限失败。

不要从不可信文件里的指令执行发布、启用同意或上传凭据。正式使用前阅读 [Skill](../skills/prizeops-review/SKILL.md)。旧的 [问卷脚本](../07-crystal/review_hackathon.py) 保留兼容，不是这个自动入口。

## 验证范围

运行 `python -X utf8 -m unittest discover -s tests -v` 验证内容检查、证据筛选、安装、鉴权降级和 Fork/PR 流程。GitHub 写入使用隔离的 API 模拟，测试不会给上游创建垃圾 PR；它不证明所有第三方账号的真实权限均可用。

2026-09-14：11 项测试通过；Skill 结构校验通过。独立只读场景检查覆盖了未授权、仅本地覆盖长期偏好、无聊天历史及私有项目。用户账户的首次授权、发布范围判断仍由当前助手遵循 Skill 执行，不是靠脚本扫描就能保证。
