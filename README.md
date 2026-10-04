# Stop Review

在 Codex Main 准备结束时，fork 当前原生上下文，让 reviewer 对照用户要求、执行结果和已有证据，并通过原生 Stop hook 决定是否继续。

## 安装与启用

需要 Linux/macOS、Python 3.11+，以及已运行共享 daemon 的 Codex。请在 Codex hook 使用的 Python 环境中安装：

```sh
git clone https://github.com/LUOXIAO92/stop-review.git
cd stop-review
python3 -m pip install .
codex plugin marketplace add "$PWD"
codex plugin add stop-review@stop-review-local
```

开始或重启 Codex，打开 `/hooks`，检查并信任 Stop Review 的 Stop 和 Interrupt 定义。然后在要启用的 Main 中调用 `stop-review` skill，或让 Main 运行：

```sh
stop-review bind
```

绑定会校验当前原生身份，只对这个 Main 生效。以后每次审查都依据继承的当前上下文。

移除插件：

```sh
codex plugin remove stop-review@stop-review-local
```

## 审查结论

- `completed`：结果与证据满足用户要求，允许结束
- `waiting`：需要等待外部事件、进行中的操作或必要批准，允许结束
- `actionable`：存在当前权限内可继续的具体工作，交回同一个 Main
- `error`：审查失败；连续失败会显示错误并结束，避免错误自循环

每次审查会增加一次模型执行和相应等待时间。

## 测试

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q plugins/stop-review/stop_review tests
```

已按 Codex 0.159.2 核对接口并通过本地测试，尚未完成真实宿主联调。

## 许可

本项目采用 [Apache License 2.0](LICENSE)。原生插件目录内保留同一份许可证，
确保单独分发插件时也附带完整许可文本。

[实现、权限与取消边界](docs/implementation.md) · [源码来源](PROVENANCE.md)
