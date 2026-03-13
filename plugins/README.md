# 插件目录说明

这个目录用于放置单文件插件。Bot 启动时会自动扫描并加载这里的插件。

## 基本约定

每个插件文件通常需要：

1. 定义一个继承 `BotModule` 的类
2. 实现 `metadata`
3. 声明 `command_capabilities`
4. 视需要实现 `config_spec`
5. 实现 `handle_mention` 和/或 `handle_slash`

如果插件依赖私有辅助模块，例如 `plugins/_xxx_service.py`，建议声明 `private_modules`，以便卸载时清理模块缓存。

## 配置文件

插件运行时配置位于：

- `config/plugins/<插件名>.json`

插件收到的 `config` 现在是 `PluginConfig` 对象，而不是裸字典。
它兼容旧写法：

- `config["key"]`
- `config.get("key")`
- `config.copy()`
- `config.to_dict()`

并额外提供：

- `config.plugin_name`
- `config.path`
- `config.exists`

## 配置资产

如果插件实现了 `config_spec`，可以自动导出：

- `config/plugins/<插件名>.example.json`
- `config/plugins/<插件名>.schema.json`

导出命令：

```bash
python tools/export_plugin_config_assets.py
python tools/export_plugin_config_assets.py delta_force
```

## 新建插件

推荐直接使用脚手架：

```bash
python tools/create_plugin_scaffold.py demo_plugin
python tools/create_plugin_scaffold.py demo_plugin --description "示例插件" --slash-command /demo
```

脚手架会自动生成：

- 插件源码骨架
- 示例配置
- 配置结构说明

## 参考插件

当前可以参考：

- `plugins/lol_ban.py`
- `plugins/lol_fa8.py`
- `plugins/delta_force.py`

## 管理员命令

- `@bot 插件列表` / `/plugins`
- `@bot 加载插件 <名>` / `/loadplugin <名>`
- `@bot 卸载插件 <名>` / `/unloadplugin <名>`

卸载和加载时，填写插件名即可，不需要带版本号文本。

## 延伸文档

完整流程说明见：

- [插件开发工作流](../docs/plugin-development.md)
