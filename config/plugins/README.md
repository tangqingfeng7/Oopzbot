# 插件配置目录

这个目录用于保存插件配置与配置资产。

## 文件类型

当前会出现 3 类文件：

- `<插件名>.json`：真实运行时配置
- `<插件名>.example.json`：示例配置
- `<插件名>.schema.json`：配置结构、默认值与约束说明

例如：

- `lol_ban.json`
- `lol_ban.example.json`
- `lol_ban.schema.json`

## 资产刷新

如果插件实现了 `config_spec`，可以通过下面的命令刷新示例和结构文件：

```bash
python tools/export_plugin_config_assets.py
python tools/export_plugin_config_assets.py delta_force lol_ban
```

## 新建插件

如果要新建一个符合当前契约的插件骨架，可以直接执行：

```bash
python tools/create_plugin_scaffold.py demo_plugin
```

脚手架会自动生成对应的 `example.json` 和 `schema.json`。

## 提交建议

建议：

- 提交 `*.example.json`
- 提交 `*.schema.json`
- 谨慎提交真实的 `<插件名>.json`

如果真实配置包含密钥、令牌或账号信息，部署时应把这些文件加入忽略规则。

## 延伸文档

完整流程说明见：

- [插件开发工作流](../../docs/plugin-development.md)
