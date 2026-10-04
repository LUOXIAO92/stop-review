# Stop Review

Codex Main 准备结束时，通过原生 `codex exec fork --ephemeral` 审查：用户要求是否由实际执行结果和证据满足。审核提示词只追加在原生继承的对话之后。

插件包含 Stop hook、一个 Python 标准库脚本和审核提示词。

## 安装

需要 Linux/macOS、Python 3.11+、Codex 0.159.2，以及能从同一 `CODEX_HOME` 访问原生历史的本地 Main。Hook 环境的 `PATH` 必须能找到 `python3` 和 `codex`。

```sh
git clone https://github.com/LUOXIAO92/stop-review.git
cd stop-review
codex plugin marketplace add "$PWD"
codex plugin add stop-review@stop-review-local
```

重启 Codex，在 `/hooks` 检查并信任 Stop Review 的 Stop 定义，即在插件安装范围内生效。

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
- `error` / 无效输出 / 原生程序失败：显示错误并停止本轮

每次审查会增加一次模型执行和等待时间。运行机制见 [实现说明](docs/implementation.md)。

## 测试

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q plugins/stop-review/scripts tests
```

本地单元测试使用临时 `codex` 测试替身，检查进程调用和 hook 响应。

## 许可

[Apache-2.0](LICENSE)。插件目录带有同一份完整许可证。[来源说明](PROVENANCE.md)。
