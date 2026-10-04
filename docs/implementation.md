# 实现说明

## 审查流程

1. 从 Codex 的 root `Stop` 事件获取当前 `session_id` 和 `model`。
2. 在相同工作目录、环境与 `CODEX_HOME` 下调用 `codex exec fork --ephemeral`，使用事件中的模型。`--skip-git-repo-check` 支持 Main 位于非 Git 目录。
3. 通过 stdin 追加审核提示词，由原生 fork 读取会话历史。
4. 获取原生 exec 的最终输出，校验 JSON 的字段、状态和 `next_steps`，转换为原生 Stop 响应。

## 运行环境

插件适用于同一机器、同一 `CODEX_HOME` 下具有可读取原生历史的本地 Main。原生 exec 会加载当前本地配置；会话历史不可读取时，审查返回错误。

审核提示词要求根据用户要求和已有执行结果、证据作出判断，仅输出审查 JSON。

## 退出与复审

reviewer 进程使用 `STOP_REVIEW_CHILD=1` 标记，hook 据此跳过嵌套审查。插件处理 Main 的 `Stop` 事件，后续 Stop 会再次审查。

脚本同步等待原生进程。Hook 的超时为 600 秒，用户中断、超时和进程树清理由原生 hook runner 处理。

## 结果

- `completed` / `waiting`：允许 Main 结束本轮。
- `actionable`：将未完成事项返回给 Main，继续执行。
- `error`、无效 JSON 或原生进程失败：显示错误并停止本轮。
