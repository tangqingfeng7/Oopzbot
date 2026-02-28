# 插件目录

将单文件插件放在此目录，bot 启动时会自动加载。

## 插件规范

1. 每个 `.py` 文件定义一个继承 `BotModule` 的类。
2. 实现 `metadata`（`PluginMetadata`）及 `mention_prefixes` 或 `slash_commands` 至少其一。
3. 实现 `handle_mention` 和/或 `handle_slash`，返回 `True` 表示已处理。
4. 若插件依赖私有辅助模块（例如 `plugins/_xxx_service.py`），请实现 `private_modules` 属性，返回完整模块名元组（如 `("plugins._xxx_service",)`），用于卸载时精确清理模块缓存。

可参考 `lol_ban.py` 或 `lol_fa8.py`。

## 配置文件

- **路径**：`config/plugins/<插件名>.json`（插件名与 `.py` 文件名一致，如 `lol_ban` → `config/plugins/lol_ban.json`）。
- **格式**：JSON 对象，内容由插件自行约定。
- **加载时机**：插件加载时读取并作为第二个参数传入 `on_load(handler, config)`；无文件或解析失败时 `config` 为 `{}`。
- **运行时重载**：在插件内可调用 `from plugin_loader import get_plugin_config`，再 `get_plugin_config("example")` 获取最新配置（每次从磁盘读取）。

示例见 `config/plugins/lol_ban.example.json` 与 `config/plugins/lol_fa8.example.json`。

## 热重载建议

- 插件在 `on_load` 中完成初始化；如有后台线程/连接资源，请在 `on_unload` 中释放。
- 对于插件私有依赖模块，建议按上面的 `private_modules` 规范声明，避免卸载/重载后仍命中旧代码。

## 管理员命令

- **@bot 插件列表** / **/plugins**：查看已加载与可加载插件。
- **@bot 加载插件 &lt;名&gt;** / **/loadplugin &lt;名&gt;**：动态加载（文件名不含 .py）。
- **@bot 卸载插件 &lt;名&gt;** / **/unloadplugin &lt;名&gt;**：卸载扩展（内置模块不可卸载）。
