# 插件配置目录

每个插件的配置文件为 `<插件名>.json`，例如：

- `lol_ban.json` → 对应插件 `plugins/lol_ban.py`
- `lol_fa8.json` → 对应插件 `plugins/lol_fa8.py`
- 格式：JSON 对象，字段由各插件自行约定

若不需要配置，可不创建该文件，插件收到的 `config` 为 `{}`。

**敏感信息**：可将 `config/plugins/` 加入 `.gitignore`，并保留 `*.example.json` 作为示例提交。
