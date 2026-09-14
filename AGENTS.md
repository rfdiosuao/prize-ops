# PrizeOps 项目协作入口

用户在本项目中明确要求“复盘”或“项目全流程复盘”时，读取并使用 `skills/prizeops-review/SKILL.md`。只是引用“复盘”一词或要求修改复盘工具时，不触发公开提交流程。

公开提交遵循 Skill 的首次同意与本次用户范围；GitHub 登录本身不代表公开许可。用户要求只本地时不发布，原始聊天、密钥和源码包不进入复盘 PR。

维护工具时运行 `python -X utf8 -m unittest discover -s tests -v`。隔离测试不要创建真实测试 PR，也不要修改本机 Git 身份或读取真实凭据来填测试。
