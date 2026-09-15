# 网页屏幕共享

屏幕共享完全运行在普通网页中，不使用 Oopz 内置共享，也不会让 Bot 加入语音频道，因此不会打断音乐播放。发起者在频道发送 `@bot 屏幕共享`，从私信打开单次链接并选择窗口、标签页或整个屏幕；浏览器成功发布后，Bot 才会在原频道发送观看链接。

## 部署要求

- 自己创建的声网 RTC 项目，并启用 App Certificate。
- 在声网控制台为该项目开启“连麦鉴权”，否则观看 Token 的禁止发布权限不会由服务端强制生效。
- 可用的 Redis。此模块不接受项目的内存 Redis 降级模式。
- 对外可访问的 HTTPS 地址；只有 `localhost` / `127.0.0.1` 可使用 HTTP 调试。
- 发起端使用桌面版 Chrome 或 Edge。观看端也推荐使用这两种浏览器。

在管理后台“配置 → 音乐与平台 → 网页屏幕共享”填写 App ID、App Certificate、链接时间、共享时长和默认画质。Certificate 保存后不会回传明文到后台页面，也不会交给浏览器；浏览器只获得服务端签发的短期 RTC Token。

`WEB_PLAYER_CONFIG["url"]` 应填写真实公网地址，例如：

```python
WEB_PLAYER_CONFIG = {
    # 其他配置省略
    "url": "https://bot.example.com",
    "cookie_secure": True,
}
```

反向代理需要原样转发 `/screen-share/`。发起和观看令牌放在 URL fragment（`#` 后）中，浏览器不会把 fragment 发送到 Web 服务器或代理访问日志。兼容路由 `/screen-share/p/{token}` 和 `/screen-share/w/{token}` 仍保留，但 Bot 自己发送的链接使用 fragment 形式。

## 域权限

进入管理后台“域管理 → 域配置”，在“屏幕共享角色”中勾选允许的身份组。配置按不可变的 `roleID` 保存，身份组改名不影响权限。

- 域主和 Bot 管理员始终允许。
- 普通成员必须至少拥有一个已勾选身份组。
- 身份组查询失败时拒绝创建共享。
- 发起者可停止自己的共享；域主、Bot 管理员和已允许角色可停止频道内共享。
- 同一文字频道允许多个用户同时共享，每个共享有独立观看链接；每个用户在所有域中仍只能发起一个会话。
- 共享者执行“停止屏幕共享”时只停止自己的会话；本人未共享时，域主、Bot 管理员或获授权角色执行该命令会停止当前频道的全部共享。

## 链接和会话生命周期

发起链接默认 10 分钟有效且只能领取一次。领取后页面通过 `createScreenVideoTrack` 打开浏览器原生窗口选择器。发起者可以选择 2K（2560×1440）、1080p 或 720p，以及最高 30/60/120/144/240 FPS；超过 30 FPS 时使用流畅优先策略。画质与帧率均作为上限：捕获后会读取源画面的实际尺寸，低于所选画质时保持源分辨率而不执行放大。实际帧率仍由共享内容、显示器刷新率、浏览器、设备性能、网络和声网链路决定。共享端不会请求麦克风权限，只发布浏览器捕获到的系统声音；系统声音不可用时会明确提示并降级为仅画面。发布成功前频道里不会出现观看链接。

共享者以 `live` 模式的 `host` 角色加入，观看者以 `audience` 角色加入，观看 Token 不包含发布权限。与控制台的“连麦鉴权”一起使用时，观看者只能订阅画面和声音，无法向频道发布音视频。

观看页采用全视口黑色播放器，完整保留共享画面的宽高比，鼠标移动时显示声音与全屏控制。观看令牌保留在 URL fragment 中且不会进入服务端访问日志，因此会话有效期间刷新页面可以重新加入；共享结束后链接立即失效。每个浏览器标签页使用独立且稳定的观看 UID，Token 续期时不会改变 UID。

发起页面每 5 秒发送心跳。网络失败时页面会持续自动重试，连续 60 秒仍未恢复、浏览器捕获结束、页面关闭、点击停止、管理员停止或达到最长共享时长时才会结束会话；观看链接随即失效。Bot 发送的频道观看链接会跟随域级/全局公告样式，不参与普通定时撤回；服务端会把其消息 ID 和时间戳保存在 Redis，仅在该共享结束时精准撤回对应链接。服务端会记录不含令牌的结束原因。声网 Token 的有效期不会超过当前共享的剩余时长；页面在过期前调用 `renewToken` 续期，临时失败时会按最长 30 秒的退避间隔自动重试。

管理后台的独立“屏幕共享”菜单会列出当前活动共享。后台为每个活动会话签发一个进程内复用的临时观看链接，重复刷新后台不会持续生成 Redis 令牌键；Redis 仍只保存令牌哈希。链接可复制或直接打开，后台管理员也可在确认后直接结束指定共享；结束后观看链接立即失效，Bot 会在原频道发送结束通知。声网凭据、默认画质等参数仍在“配置 → 音乐与平台 → 网页屏幕共享”中维护。

“屏幕共享已结束”提示遵循全局 `AUTO_RECALL_CONFIG` 设置：开启时按 `delay` 撤回，关闭时保留。开始消息中的观看链接仍保留至该次共享结束。

Linux/Wayland 浏览器通常不能捕获系统声音，这种情况下会自动退化为仅画面。浏览器的共享窗口中只有明确勾选“共享标签页音频”或系统提供相应音频选项时，才能获得系统声音。

## 路由与源码布局

| 类型 | 路径 | 用途 |
|------|------|------|
| 页面 | `GET /screen-share/p` | 发起端，单次令牌位于 URL fragment |
| 页面 | `GET /screen-share/w` | 只读观看端，观看令牌位于 URL fragment |
| 发起端 API | `POST /screen-share/api/presenter/{claim,ready,heartbeat,renew,stop}` | 领取、就绪、心跳、Token 续期与停止 |
| 观看端 API | `POST /screen-share/api/viewer/token` | 签发只读 RTC Token |
| 后台 API | `GET /admin/api/screen-shares` | 列出活动共享及后台观看链接 |
| 后台 API | `POST /admin/api/screen-shares/{session_id}/stop` | 结束指定共享，需后台登录 |

```text
src/screen_share/
├── service.py          # Redis 会话、权限、Token 与过期清理
├── agora_token.py      # 声网 AccessToken2 签发
├── labels.py           # 发起者名称解析
├── messages.py         # 观看链接消息引用与结束时撤回
├── web.py              # 发起/观看页 API 与看门狗
└── client/             # TypeScript 源码和构建配置

src/web/admin/screen_share.py                  # 后台列表与停止接口
src/web/assets/admin/pages/screen-share_*       # 后台屏幕共享页
src/web/assets/screen-share/                    # 随仓库发布的浏览器编译产物
```

## 前端开发

正式部署直接使用仓库内已提交的 `src/web/assets/screen-share/app.js`，无需安装 Node.js。只有修改 TypeScript 源码时才需要：

```bash
cd src/screen_share/client
npm ci
npm run typecheck
npm run build
```

源码与构建配置收口在屏幕共享模块的 `src/screen_share/client/`，编译产物输出到 `src/web/assets/screen-share/app.js`。

## 验收

配置真实凭据和 HTTPS 后，用两个浏览器验证：发起端选择一个有动态内容且提供系统音频的窗口，观看端从频道链接打开，确认画面、系统声音、停止通知和链接失效。测试时不要把 Certificate、RTC Token 或私信发起链接复制到日志或频道。
