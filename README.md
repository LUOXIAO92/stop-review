# Stop Review

Codex Main 准备结束时，通过原生 `codex exec fork --ephemeral` 审查：用户要求是否由实际执行结果和证据满足。审核提示词只追加在原生继承的对话之后。

插件只有 Stop hook、一个 Python 标准库脚本和审核提示词。没有自建 runtime、RPC 客户端、会话管理、独立 CLI、绑定步骤或 skill。

## 安装

需要 Linux/macOS、Python 3.11+、Codex 0.159.2，以及能从同一 `CODEX_HOME` 访问原生历史的本地 Main。Hook 环境的 `PATH` 必须能找到 `python3` 和 `codex`。

```sh
git clone https://github.com/LUOXIAO92/stop-review.git
cd stop-review
codex plugin marketplace add "$PWD"
codex plugin add stop-review@stop-review-local
```

重启 Codex，在 `/hooks` 检查并信任 Stop Review 的 Stop 定义，即在插件安装范围内生效。无需 pip 安装或 Main 绑定。旧版升级也无需保留 Python 包或绑定记录；新版本不会读取它们。

移除：

```sh
codex plugin remove stop-review@stop-review-local
```

## 工作方式

Hook 直接调用已安装的原生程序：

```sh
codex exec fork --ephemeral --model="$MODEL" --skip-git-repo-check "$SESSION_ID" -
```

`MODEL` 和 `SESSION_ID` 来自当前原生 Stop 事件；审核提示词通过 stdin 输入。原生 Codex 负责 fork、运行与退出；脚本只校验最终 JSON 并返回原生 Stop 响应。

- `completed` / `waiting`：允许结束
- `actionable`：将具体未完成事项交回同一个 Main；后续 Stop 仍会复审
- `error` / 无效输出 / 原生程序失败：显示错误并停止本轮，不冒充审查通过

每次审查会增加一次模型执行和等待时间。`--ephemeral` 使用原生父缓存路由；不额外设置输出 schema、沙箱、审批或工具开关。原生 exec 仍会重新加载本地配置，因此不能保证与 Main 的完整模型输入逐字一致或缓存必然命中。具体范围见 [实现边界](docs/implementation.md)。

## 验证

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q plugins/stop-review/scripts tests
```

14 项本地测试通过；已核对已安装 0.159.2 CLI 帮助和对应官方源码。测试替身验证进程调用和 hook 响应，未运行真实用户会话、模型审查或缓存命中测试。

## 许可

[Apache-2.0](LICENSE)。插件目录带有同一份完整许可证。[来源说明](PROVENANCE.md)。
