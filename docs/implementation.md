# 实现与验证

## 宿主条件

实现基于 Codex 0.159.2 的原生 Stop/Interrupt hook 与 app-server proxy。
支持 Linux/macOS、Python 3.11+、websockets 15–16；需要已运行的共享 daemon，
以及 Main 执行环境中的 CODEX_THREAD_ID 和正确的 CODEX_HOME。
未测试其它版本、Windows、远程 daemon 或 --no-daemon。缺少所需接口会报错。

如果使用虚拟环境，宿主 daemon 的 hook 环境也需要找到同一环境的 python3。
仅在另一个终端激活环境不会改变已有 daemon 的 PATH。

## 实现边界


- 保留 native Stop → 当前 Main 上下文 fork → reviewer → schema 校验 → native Stop response。原始 developer instructions 和历史由宿主继承，不读取会话文件、不拼装一份摘要来冒充完整上下文。
- `excludeTurns: true` 只避免 RPC 响应加载历史，不删除 fork 的继承上下文。模型取 Stop 事件的实际 model，provider 取原生线程，并校验 fork 返回值。
- fork 收紧为 read-only sandbox，不批准 client 请求。reviewer 指令要求不使用工具、不执行工作。原生/MCP 的 server-side 工具并不全部经过此客户端，因此这不是通用“禁用所有工具”的安全隔离；继承的更高优先级指令仍然有效。
- 新 fork 先暂停继承目标的自动运行，再清除并确认该 reviewer 的目标为空。宿主明确返回 goals 功能未开启时也可继续。Main 的目标不变。
- fork 可能共享 `session_id`。每次审查前后都核对绑定 Main 的精确活跃 turn；reviewer 的 Stop 不能递归触发审查，过期结果不能唤醒已停止的 Main。代码从不对 Main 发起 turn/start、resume 或 interrupt。
- SIGINT/SIGTERM、审查超时和不确定的 turn/start 响应会尝试确认并取消确切的 reviewer turn。480 秒整体工作期限从连接前开始，给 600 秒 Stop hook 保留清理余量。
- 独立 Interrupt hook 在 Main 被用户中断后按父 turn 找到 reviewer，在宿主允许的短时间内清理。它最多尝试约 2 秒，未确认会通过 systemMessage 报告。宿主/进程崩溃、SIGKILL、控制通道失联，以及 start 与 Interrupt 同时发生的竞争，仍可能使清理无法确认；不会宣称此时 reviewer 已停止。没有常驻 watchdog。

只在 `$CODEX_HOME/stop-review/` 保存绑定、reviewer 身份和实际输出/usage。文件为 0600，状态目录为 0700。记录可能含任务内容，请按本地会话资料保护；不读取私有 session/rollout 文件、不保存凭据。它不是对同一 OS 用户的防伪边界。已有 hook、宿主配置和远程仓库均不被本包自动修改。

## 验证范围

本地执行环境：Python 3.12.14、websockets 16.0。26 个 unittest 方法全部通过，
另通过 compileall、JSON/路径/提示词检查，以及断网、无依赖安装的 wheel 构建。
未安装本插件到真实 Codex 宿主，未发起真实模型审查。

测试 peer 由本包提供，通过真实 WebSocket 字节协议替代 Codex 可执行程序，不调用模型、不运行用户项目。覆盖判断、原生 fork 参数、schema、递归、身份、过期 turn、错误边界、取消、丢失/畸形 start 响应、Interrupt 清理与安装路径。这些测试不等于真实宿主联调。

真实启用后建议先用低风险任务分别检查：正常完成；明确未完成的授权工作被退回；用户中断不继续；reviewer 自身不会再次 fork。可在 `/hooks` 查看注册与信任状态。每次触发实际审查会增加一次模型执行与等待时间，缓存命中和节省成本都不保证。

## 参考

- [插件与 marketplace 格式](https://developers.openai.com/plugins/build/plugins)
- [原生 hooks 与 Interrupt 限制](https://learn.chatgpt.com/docs/hooks)
- [App Server RPC](https://learn.chatgpt.com/docs/app-server)
- 源码来源与许可状态见 [PROVENANCE.md](../PROVENANCE.md)
