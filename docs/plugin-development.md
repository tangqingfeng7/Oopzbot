# 插件开发工作流

这份文档说明当前项目里的插件开发约定，以及新插件从创建到落盘配置资产的标准流程。

## 目标

当前插件体系已经不再只是“把一个 `.py` 文件丢进 `plugins/` 目录”。
插件开发现在有 3 个稳定目标：

- 契约统一：命令能力、元数据、配置规范都走显式模型
- 资产统一：示例配置和结构说明由代码自动导出
- 流程统一：新增插件时优先走脚手架，而不是复制旧文件

## 插件契约

插件基础契约定义在 `src/domain/plugins/base.py`。

一个标准插件通常需要实现这些部分：

- `metadata`
- `command_capabilities`
- `config_spec`
- `dispatch_command`（继承 `PluginCommandMixin`，见下方「命令入口」）
- `on_load`
- `on_unload`

需要在手动卸载前清理业务状态时，可实现 `on_disable`。它在插件仍注册时运行，抛出异常会中止卸载。应用关闭时调用 `on_unload` 释放运行时资源。

Web 插件可在 `on_load` 中调用 `handler.register_web(router, admin_nav=...)`，把 FastAPI 路由和可选的后台导航项注册到宿主。保存返回的注销函数，在 `on_unload` 中调用。页面和 API 路由由插件声明，后台 API 使用 `/admin/api/` 路径以沿用后台认证。

### 命令入口

命令入口统一走 `plugins/_shared/command_mixin.py` 的 `PluginCommandMixin`：插件类同时继承
`PluginCommandMixin` 和 `BotModule`，只需实现 `dispatch_command`，mention 前缀与 slash 命令名
会按 `command_capabilities` 自动剥离匹配，异常也由 mixin 统一捕获并回复。错误文案与日志通道
用类属性 `command_error_prefix` / `command_log_name` 定制：

```python
from plugins._shared.command_mixin import PluginCommandMixin


class FooPlugin(PluginCommandMixin, BotModule):
    command_error_prefix = "Foo 查询出错"
    command_log_name = "FooPlugin"

    async def dispatch_command(self, command_text, channel, area, user, handler):
        await self._send(handler, "处理完成", channel, area)
```

只有需要特殊路由的插件（例如 arc 的 `/arcevent` 走独立截图逻辑）才自行覆盖 `handle_slash`；
普通插件不要再手写 `handle_mention` / `handle_slash`。

需要响应普通聊天消息（不是 @bot 也不是 / 命令）的插件覆盖 `async def handle_message(text, channel, area, user, handler) -> bool`，
返回 `True` 表示已处理，后续插件不再收到这条消息，参考 `keyword_reply`。

最核心的几个模型：

- `PluginMetadata`
- `PluginCommandCapabilities`
- `PluginConfig`
- `PluginConfigSpec`

如果插件依赖私有辅助模块，例如 `plugins/demo_plugin/service.py`，建议声明 `private_modules`，方便卸载时清理模块缓存。

## 配置规范

插件运行时收到的 `config` 已经不是裸 `dict`，而是 `PluginConfig`。
它提供这些常见读取方式：

- `config["key"]`
- `config.get("key")`
- `config.copy()`
- `config.to_dict()`

同时还包含结构化信息：

- `config.plugin_name`
- `config.path`
- `config.exists`

推荐新插件都显式实现 `config_spec`。这样可以把默认值、必填项和字段约束集中到一个地方维护。

当前常用能力包括：

- 默认值合并
- 必填校验
- 类型转换
- 枚举约束
- 时间格式校验
- URL 列表校验
- 数值范围校验

## 配置资产

如果插件实现了 `config_spec`，就可以自动导出两类配置资产：

- `config/plugins/<插件名>/example.json`
- `config/plugins/<插件名>/schema.json`

它们的作用分别是：

- `example.json`：给人看，作为示例配置
- `schema.json`：给人和工具看，描述字段、默认值和约束

刷新命令：

```bash
python tools/export_plugin_config_assets.py
python tools/export_plugin_config_assets.py delta_force lol_ban
```

## 共享基类

`plugins/_shared/` 提供了插件间复用的基类，避免每个插件重复造轮子：

- `PluginCommandMixin`（`_shared/command_mixin.py`）：统一的 mention/slash 命令入口。插件继承它后只需实现 `dispatch_command`，前缀剥离、slash 匹配、异常包装与统一发送都由 mixin 完成。当前全部插件均采用此写法（参考 `apex`、`steam_price`、`lol_ban` 等），新插件请遵循。
- `IntervalWorker`（`_shared/background.py`）：按固定间隔运行的可取消 `asyncio.Task` 基类，统一封装「启动一次 / 停止 / 间隔轮询」生命周期。子类实现 `async def _tick()`，在合适时机调用 `_start_task()`，卸载时 `await stop()`；长循环里可用 `self.stopping` 提前退出。适合定时推送和轮询监控（参考 `delta_force/daily_push.py`、`steam_price/monitor.py`）。
- `JsonHttpClient`（`_shared/http_client.py`）：带重试与 JSON 解析的异步 HTTP 客户端基类，统一封装 User-Agent、超时、代理与重试循环。通过 `await request_json(method, url, ...)` 发起请求，成功返回解析后的 JSON，网络异常重试耗尽或 JSON 解析失败返回 `{"_error": ...}`；`on_status` 回调可拦截 404/429 等状态码（参考 `apex/api.py`、`steam_price/api.py`）。

另外，默认值应以 `config_spec` 为单一来源——若需要在 service 层拿到默认配置，可从 `config_spec.fields` 派生，而不要再单独维护一份 `_DEFAULT_CONFIG` 字典（参考 `lol_ban` / `lol_fa8`）。

## 新建插件

推荐直接使用脚手架工具：

```bash
python tools/create_plugin_scaffold.py demo_plugin
python tools/create_plugin_scaffold.py demo_plugin --description "示例插件" --slash-command /demo
python tools/create_plugin_scaffold.py admin_demo --admin-only
```

脚手架会自动生成：

- `plugins/<插件名>/__init__.py`
- `config/plugins/<插件名>/example.json`
- `config/plugins/<插件名>/schema.json`

默认骨架会带上：

- 标准 `metadata`
- 标准 `command_capabilities`
- 最小 `config_spec`
- 同时继承 `PluginCommandMixin` 与 `BotModule` 的插件类
- 待实现的 `dispatch_command`；`handle_mention` / `handle_slash` 由 mixin 统一处理

## 推荐开发流程

1. 先用脚手架创建插件骨架。
2. 补充 `metadata`、`command_capabilities` 和 `config_spec`。
3. 用 `async def` 实现业务逻辑和 `on_load / on_config_reload / on_unload`，所有发送、HTTP 与数据库调用都直接 `await`。
4. 运行配置资产导出命令。
5. 补测试，至少覆盖能力声明和配置资产一致性。

## 提交前检查

建议至少执行：

```bash
python tools/export_plugin_config_assets.py
python -m unittest tests.test_plugin_config_layout tests.test_plugin_runtime_state
```

如果插件改动影响主链，再跑全量测试。

## 现状说明

当前仓库里的插件已经按“一插件一目录”的方式收口。
后续新增插件，建议默认遵守这份文档，而不是继续复制历史插件文件再手工删改。
