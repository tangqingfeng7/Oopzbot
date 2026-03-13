# 插件开发工作流

这份文档说明当前项目里的插件开发约定，以及新插件从创建到落盘配置资产的标准流程。

## 目标

当前插件体系已经不再只是“把一个 `.py` 文件丢进 `plugins/` 目录”。
插件开发现在有 3 个稳定目标：

- 契约统一：命令能力、元数据、配置规范都走显式模型
- 资产统一：示例配置和结构说明由代码自动导出
- 流程统一：新增插件时优先走脚手架，而不是复制旧文件

## 插件契约

插件基础契约定义在 `src/plugin_base.py`。

一个标准插件通常需要实现这些部分：

- `metadata`
- `command_capabilities`
- `config_spec`
- `handle_mention`
- `handle_slash`
- `on_load`
- `on_unload`

最核心的几个模型：

- `PluginMetadata`
- `PluginCommandCapabilities`
- `PluginConfig`
- `PluginConfigSpec`

如果插件依赖私有辅助模块，例如 `plugins/_xxx_service.py`，建议声明 `private_modules`，方便卸载时清理模块缓存。

## 配置规范

插件运行时收到的 `config` 已经不是裸 `dict`，而是 `PluginConfig`。
它仍然兼容常见字典写法：

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

- `config/plugins/<插件名>.example.json`
- `config/plugins/<插件名>.schema.json`

它们的作用分别是：

- `example.json`：给人看，作为示例配置
- `schema.json`：给人和工具看，描述字段、默认值和约束

刷新命令：

```bash
python tools/export_plugin_config_assets.py
python tools/export_plugin_config_assets.py delta_force lol_ban
```

## 新建插件

推荐直接使用脚手架工具：

```bash
python tools/create_plugin_scaffold.py demo_plugin
python tools/create_plugin_scaffold.py demo_plugin --description "示例插件" --slash-command /demo
python tools/create_plugin_scaffold.py admin_demo --admin-only
```

脚手架会自动生成：

- `plugins/<插件名>.py`
- `config/plugins/<插件名>.example.json`
- `config/plugins/<插件名>.schema.json`

默认骨架会带上：

- 标准 `metadata`
- 标准 `command_capabilities`
- 最小 `config_spec`
- 空实现的 `handle_mention / handle_slash`

## 推荐开发流程

1. 先用脚手架创建插件骨架。
2. 补充 `metadata`、`command_capabilities` 和 `config_spec`。
3. 实现业务逻辑和 `on_load / on_unload`。
4. 运行配置资产导出命令。
5. 补测试，至少覆盖能力声明和配置资产一致性。

## 提交前检查

建议至少执行：

```bash
python tools/export_plugin_config_assets.py
python -m unittest tests.test_plugin_contract_behavior tests.test_plugin_config_assets tests.test_plugin_scaffold
```

如果插件改动影响主链，再跑全量测试。

## 现状说明

当前仓库里 `lol_ban`、`lol_fa8`、`delta_force` 已经开始按这套流程收口。
后续新增插件，建议默认遵守这份文档，而不是继续复制历史插件文件再手工删改。
