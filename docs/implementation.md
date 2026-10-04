# 实现边界

## 原生路径

1. Codex 的 root `Stop` 事件提供本轮 `session_id` 和实际 `model`。0.159.2 的 root session ID 等于 root thread ID；`SubagentStop` 不触发本插件。不使用可能来自 daemon 启动环境的 `CODEX_THREAD_ID` 猜 Main。
2. 同一工作目录、环境与 `CODEX_HOME` 下调用原生 `codex exec fork --ephemeral`，明确使用本轮模型。`--skip-git-repo-check` 仅允许 Main 位于非 Git 目录。
3. Prompt 只通过 stdin 追加；不读取、复制或重建会话历史，不覆盖 system/developer instructions，不传 `--output-schema`，不额外覆盖 provider、权限、工具或推理参数。
4. 原生 exec 的 stdout 为最终消息，stderr 为诊断。仅在退出码为零且完整输出通过严格本地 JSON 校验后，转换为原生 Stop response。拒绝重复字段、额外字段、无效状态及不一致的 next_steps。

## 上下文与缓存

普通本地持久化 Main 进入 Stop 时，原生 `hook_transcript_path` 会先 materialize/persist 当前历史。exec 的独立进程通过原生 fork 读取该历史；插件不使用摘要代替上下文。仅在内存中的会话、其它机器的历史或无法读取的历史不受支持，原生失败会显式报告。

原生持久化失败可能仅产生宿主警告，所以不能把 fork 成功本身当作“最新历史完整”的独立验证。审核提示词也区分 fork 快照插入的中断标记与用户真实的取消指令。

`--ephemeral` 让原生 root fork 使用父缓存路由，并避免持久化 reviewer；该分支不继承 Main 的自动目标。插件不自建 cache key 或生命周期。

原生 exec 0.159.2 会重新加载当前本地配置，并向 fork 传入 model/provider、cwd、workspace roots 和权限；无 AutoReview 时 headless 审批默认为 never。这些是原生程序行为，不能从 Stop payload 还原 Main 的临时 profile、provider、reasoning 设置或 live instruction provider。原生历史有 base instructions 和 dynamic tool schema 的继承路径，但 exec 拒绝动态工具调用。故没有“与 Main 完全相同输入前缀”的保证，更没有 KV cache 克隆或必然命中的保证。

审核提示词要求只比较用户要求与已有结果/证据，不执行工作、不调用工具、不产生新授权。此限制是提示词约束，不是另建的权限沙箱；继承的更高优先级指令仍然有效。

## 递归、超时与退出

仅为 reviewer 进程设置 `STOP_REVIEW_CHILD=1`；原生 hook 环境继承此标记，本脚本因此不再次 fork。不全局禁用 hooks，不用 `stop_hook_active` 跳过 Main 后续复审。不会写绑定、reviewer 注册表、状态文件或单独的输出文件。

脚本同步等待原生进程，保持在宿主 hook 的进程组内。600 秒 hook deadline、用户中断及进程树清理由原生 hook runner 负责；不 detach、不建 watcher、不增加 Interrupt hook、不对 Main 调用 resume/start。超时由宿主报告为 hook 失败，而非本地 JSON 审查结果；不声称此时已收到 reviewer 的取消确认。

## 验证范围

14 个 unittest 使用临时 fake `codex` 可执行程序，覆盖确切参数和 stdin、模型与 root 身份、环境/工作目录/进程组、四类结论、后续复审、防递归、非 Stop 事件、缺失程序、原生失败、严格 JSON 和最小插件结构。它们不证明真实宿主调用、所有中断场景或缓存表现。

接口依据已安装 `codex-cli 0.159.2` 的 `exec fork --help`、plugin 命令帮助和同版官方源码；源码定位见 [PROVENANCE.md](../PROVENANCE.md)。
