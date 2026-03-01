"""
命令解析与路由
支持 @bot 中文指令 和 / 开头的命令
"""

import re
import threading
import time
from typing import Optional

from config import OOPZ_CONFIG, ADMIN_UIDS, PROFANITY_CONFIG
try:
    from config import AUTO_RECALL_CONFIG
except ImportError:
    AUTO_RECALL_CONFIG = {"enabled": False}
from oopz_sender import OopzSender
from chat import ChatHandler
from logger_config import get_logger
from plugin_registry import PluginRegistry
from plugin_loader import load_plugins_dir as loader_load_plugins_dir, load_plugin, unload_plugin, discover_plugins

logger = get_logger("CommandHandler")

# Bot 自身的 @mention 标记
_BOT_UID = OOPZ_CONFIG.get("person_uid", "")
_BOT_MENTION = f"(met){_BOT_UID}(met)" if _BOT_UID else ""


class CommandHandler:
    """
    消息命令路由器。

    在 main.py 中将此实例的 handle() 方法注册为 OopzClient 的消息回调。
    """

    def __init__(self, sender: OopzSender, voice_client=None):
        self.sender = sender
        self.chat = ChatHandler()
        self._music = None  # 延迟导入，避免循环依赖
        self._voice_client = voice_client
        self._recent_messages = []  # 记录最近的消息（最多保留50条）
        self._profanity_warnings: dict[str, int] = {}  # uid -> 警告次数（warn_before_mute 模式用）
        self._profanity_keywords = [k.lower() for k in PROFANITY_CONFIG.get("keywords", [])]
        self._user_msg_buffer: dict[str, list[dict]] = {}  # uid -> 最近消息列表（上下文检测用）
        self._plugin_registry = PluginRegistry()
        loader_load_plugins_dir(self._plugin_registry, "plugins", handler=self)

    # 所有人均可使用的指令关键词（@bot 中文指令前缀 + / 命令）
    _PUBLIC_MENTION_PREFIXES = ("每日一句", "一句", "名言", "语录", "鸡汤",
                                "画", "画一个", "画一张", "生成图片", "生成", "画图",
                                "帮助", "help", "指令", "命令",
                                "个人信息", "我是谁", "信息",
                                "我的资料", "我的详细资料", "我的信息")
    _PUBLIC_COMMANDS = ("/daily", "/quote", "/help",
                        "/me", "/myinfo")

    @staticmethod
    def _is_admin(user: str) -> bool:
        """检查用户是否为授权管理员。ADMIN_UIDS 为空时不做限制。"""
        if not ADMIN_UIDS:
            return True
        return user in ADMIN_UIDS

    def _is_public_command(self, content: str) -> bool:
        """检查是否为公共指令（无需管理员权限）。"""
        if _BOT_MENTION and _BOT_MENTION in content:
            text = content.replace(_BOT_MENTION, "").strip()
            if any(text.startswith(p) for p in self._PUBLIC_MENTION_PREFIXES):
                return True
            return self._plugin_registry.has_public_mention_prefix(text)
        if content.startswith("/"):
            cmd = content.split()[0].lower()
            if cmd in self._PUBLIC_COMMANDS:
                return True
            return self._plugin_registry.has_public_slash_command(cmd)
        return False

    # 形近字/谐音字归一化映射（替换字 → 原字）
    _CHAR_NORMALIZE = str.maketrans({
        # 繁体 → 简体
        "艹": "草", "屄": "逼", "馬": "马", "嗎": "吗",
        "媽": "妈", "罵": "骂", "幹": "干", "機": "鸡",
        "雞": "鸡", "賤": "贱", "個": "个", "殺": "杀",
        "腦": "脑", "殘": "残", "滾": "滚",
        # 谐音替代（不易误伤的）
        "糙": "草", "槽": "草",
        "批": "逼",
        "肏": "操",
        # emoji → 汉字
        "🐎": "马", "🐴": "马", "🐕": "狗", "🐶": "狗",
        "🐔": "鸡", "🐂": "牛", "🐷": "猪", "💀": "死",
        "🖕": "操",
        # 打码/干扰符号
        "*": "", "#": "", "@": "", "×": "",
    })

    @classmethod
    def _clean_text(cls, content: str) -> str:
        """清理文本：去 @mention、去干扰符号、字符归一化，用于脏话匹配。"""
        text = re.sub(r"\(met\)\w+\(met\)", "", content)
        text = re.sub(r"[\s\u200b\u200c\u200d\ufeff.,!?，。！？~·、\-_=+]+", "", text)
        text = text.translate(cls._CHAR_NORMALIZE)
        return text.lower()

    def _check_profanity(self, content: str) -> Optional[str]:
        """检测单条消息是否包含脏话，返回命中的关键词或 None。"""
        text = self._clean_text(content)
        for kw in self._profanity_keywords:
            if kw in text:
                return kw
        return None

    def _push_user_buffer(self, user: str, content: str, message_id: str,
                          channel: str, area: str, timestamp: str):
        """将消息加入用户的上下文缓冲区，并清理过期条目。"""
        now = time.time()
        window = PROFANITY_CONFIG.get("context_window", 30)
        max_msgs = PROFANITY_CONFIG.get("context_max_messages", 10)

        buf = self._user_msg_buffer.setdefault(user, [])
        buf.append({
            "content": content,
            "message_id": message_id,
            "channel": channel,
            "area": area,
            "timestamp": timestamp,
            "time": now,
        })
        # 清理过期和超量条目
        cutoff = now - window
        self._user_msg_buffer[user] = [
            m for m in buf if m["time"] >= cutoff
        ][-max_msgs:]

    def _check_context_profanity(self, user: str) -> Optional[tuple[str, list[dict]]]:
        """
        拼接用户最近消息检测脏话（上下文检测）。
        返回 (命中关键词, 涉及的消息列表) 或 None。
        """
        buf = self._user_msg_buffer.get(user, [])
        if len(buf) < 2:
            return None

        # 从最近的消息开始，逐步向前扩展拼接范围
        for start in range(len(buf) - 2, -1, -1):
            segment = buf[start:]
            combined = "".join(self._clean_text(m["content"]) for m in segment)
            for kw in self._profanity_keywords:
                if kw in combined:
                    return kw, segment
        return None

    _MUTE_THRESHOLDS = [1, 5, 60, 1440, 4320, 10080]

    @classmethod
    def _actual_mute_duration(cls, minutes: int) -> int:
        """返回 API 实际生效的禁言时长（分钟）。"""
        for limit in cls._MUTE_THRESHOLDS:
            if minutes <= limit:
                return limit
        return cls._MUTE_THRESHOLDS[-1]

    @staticmethod
    def _format_duration(minutes: int) -> str:
        """将分钟数格式化为人类可读的时长。"""
        if minutes < 60:
            return f"{minutes} 分钟"
        if minutes < 1440:
            return f"{minutes // 60} 小时"
        return f"{minutes // 1440} 天"

    def _handle_profanity(self, user: str, channel: str, area: str,
                          matched: str, messages: list[dict]):
        """处理脏话消息：撤回涉及的所有消息 + 警告/禁言。"""
        from name_resolver import NameResolver
        name = NameResolver().user(user) or user[:8]
        duration = PROFANITY_CONFIG.get("mute_duration", 5)
        actual = self._actual_mute_duration(duration)
        display = self._format_duration(actual)

        if PROFANITY_CONFIG.get("recall_message"):
            for msg in messages:
                mid = msg.get("message_id")
                if mid:
                    self.sender.recall_message(
                        mid, area=msg.get("area", area),
                        channel=msg.get("channel", channel),
                        timestamp=msg.get("timestamp", ""),
                    )

        # warn_before_mute 模式：第一次警告，第二次禁言
        if PROFANITY_CONFIG.get("warn_before_mute"):
            count = self._profanity_warnings.get(user, 0) + 1
            self._profanity_warnings[user] = count
            if count < 2:
                self.sender.send_message(
                    f"[!] {name} 请文明发言，再犯将被禁言 {display}",
                    channel=channel, area=area,
                )
                return
            self._profanity_warnings[user] = 0

        result = self.sender.mute_user(user, area=area, duration=duration)
        if "error" in result:
            logger.warning(f"自动禁言 {name} 失败: {result['error']}")
            self.sender.send_message(
                f"[!] {name} 发送违规内容，自动禁言失败",
                channel=channel, area=area,
            )
        else:
            logger.info(f"自动禁言: {name} 触发关键词 [{matched}]（{len(messages)}条消息），禁言 {display}")
            self.sender.send_message(
                f"[!] {name} 因发送违规内容被自动禁言 {display}",
                channel=channel, area=area,
            )

        # 清空该用户的缓冲区
        self._user_msg_buffer.pop(user, None)

    @staticmethod
    def _skip_auto_recall(command_type: str) -> Optional[bool]:
        """
        检查指定命令类型是否应跳过自动撤回。
        返回 False 表示跳过自动撤回，None 表示使用默认行为。
        """
        if AUTO_RECALL_CONFIG.get("enabled"):
            exclude = AUTO_RECALL_CONFIG.get("exclude_commands", [])
            if command_type in exclude:
                return False
        return None

    def _schedule_user_msg_recall(self, message_id: str, channel: str, area: str, timestamp: str = ""):
        """自动撤回开启时，延迟后撤回用户的指令消息"""
        if not message_id:
            return
        if not AUTO_RECALL_CONFIG.get("enabled"):
            return
        delay = AUTO_RECALL_CONFIG.get("delay", 30)
        if delay <= 0:
            return
        timer = threading.Timer(
            delay, self.sender.recall_message,
            kwargs={"message_id": message_id, "area": area, "channel": channel, "timestamp": timestamp},
        )
        timer.daemon = True
        timer.start()

    @property
    def music(self):
        if self._music is None:
            from music import MusicHandler
            self._music = MusicHandler(self.sender, voice=self._voice_client)
        return self._music

    def handle(self, msg_data: dict):
        """
        处理一条聊天消息。

        msg_data 结构::
            {
                "channel": "频道ID",
                "person": "用户ID",
                "content": "消息文本",
                "messageId": "消息ID",
                ...
            }
        """
        content = (msg_data.get("content") or "").strip()
        channel = msg_data.get("channel")
        area = msg_data.get("area")
        user = msg_data.get("person")
        message_id = msg_data.get("messageId")

        # 记录消息历史（用于撤回功能）
        if message_id:
            self._recent_messages.append({
                "messageId": str(message_id) if message_id is not None else "",
                "channel": channel,
                "area": area,
                "content": content[:50],
                "user": user,
                "timestamp": msg_data.get("timestamp", ""),
            })
            if len(self._recent_messages) > 50:
                self._recent_messages.pop(0)

        if not content:
            return

        # 脏话自动禁言检测（在命令处理之前）
        if PROFANITY_CONFIG.get("enabled"):
            skip = PROFANITY_CONFIG.get("skip_admins") and self._is_admin(user)
            if not skip and user != _BOT_UID:
                ts = msg_data.get("timestamp", "")
                msg_ref = [{"message_id": message_id, "channel": channel,
                            "area": area, "timestamp": ts}]

                # 1) 单条消息关键词检测
                matched = self._check_profanity(content)
                if matched:
                    self._handle_profanity(user, channel, area, matched, msg_ref)
                    return

                # 2) 上下文拼接检测（防止拆字发送）
                use_context = PROFANITY_CONFIG.get("context_detection") or PROFANITY_CONFIG.get("ai_detection")
                if use_context:
                    self._push_user_buffer(user, content, message_id, channel, area, ts)
                if PROFANITY_CONFIG.get("context_detection"):
                    ctx = self._check_context_profanity(user)
                    if ctx:
                        matched_kw, involved_msgs = ctx
                        self._handle_profanity(user, channel, area, matched_kw, involved_msgs)
                        return

                # 3) AI 辅助检测（关键词和上下文都未命中时）
                if PROFANITY_CONFIG.get("ai_detection"):
                    min_len = PROFANITY_CONFIG.get("ai_min_length", 2)

                    # 3a) 单条消息 AI 检测
                    clean = self._clean_text(content)
                    if len(clean) >= min_len:
                        logger.info(f"AI 审核单条: \"{content[:30]}\" (长度={len(clean)})")
                        reason = self.chat.check_profanity(content)
                        if reason:
                            logger.info(f"AI 检测到违规: {content[:30]} -> {reason}")
                            self._handle_profanity(user, channel, area, f"AI:{reason}", msg_ref)
                            return

                    # 3b) 上下文拼接后 AI 检测（防止一字一条绕过）
                    buf = self._user_msg_buffer.get(user, [])
                    if len(buf) >= 2:
                        combined = "".join(m["content"] for m in buf)
                        combined_clean = self._clean_text(combined)
                        if len(combined_clean) >= min_len:
                            logger.info(f"AI 审核上下文: \"{combined[:40]}\" ({len(buf)}条拼接, 长度={len(combined_clean)})")
                            reason = self.chat.check_profanity(combined)
                            if reason:
                                logger.info(f"AI 上下文检测到违规: {combined[:40]} -> {reason}")
                                self._handle_profanity(user, channel, area, f"AI:{reason}", list(buf))
                                return

        is_command = (
            (_BOT_MENTION and _BOT_MENTION in content)
            or content.startswith("/")
        )

        if is_command and not self._is_admin(user) and not self._is_public_command(content):
            logger.info(f"非管理员用户 {user} 尝试执行指令: {content[:40]}")
            self.sender.send_message(
                "[x] 无权限，仅管理员可使用指令",
                channel=channel, area=area,
            )
            return

        # @bot 中文指令
        if _BOT_MENTION and _BOT_MENTION in content:
            text = content.replace(_BOT_MENTION, "").strip()
            if text:
                self._dispatch_mention(text, channel, area, user)
            self._schedule_user_msg_recall(message_id, channel, area, msg_data.get("timestamp", ""))
            return

        # / 开头的命令
        if content.startswith("/"):
            self._dispatch_command(content, channel, area, user)
            self._schedule_user_msg_recall(message_id, channel, area, msg_data.get("timestamp", ""))
            return

        # 非命令消息 → 聊天自动回复
        reply = self.chat.try_reply(content)
        if reply:
            self.sender.send_message(reply, channel=channel, area=area)

    # ------------------------------------------------------------------
    # @bot 中文指令分发
    # ------------------------------------------------------------------

    def _dispatch_mention(self, text: str, channel: str, area: str, user: str):
        """解析 @bot 后面的中文指令"""
        if self._plugin_registry.try_dispatch_mention(text, channel, area, user, self):
            return

        # 播放 <歌名>
        for prefix in ("播放", "放", "点播", "来一首", "听"):
            if text.startswith(prefix):
                keyword = text[len(prefix):].strip()
                if keyword:
                    self.music.play_netease(keyword, channel, area, user)
                else:
                    self.sender.send_message("请输入歌名，例如: @bot 播放海阔天空", channel=channel, area=area)
                return

        # 停止 / 停
        if text in ("停止", "停", "停止播放", "关"):
            self.music.stop_play(channel, area)
            return

        # 下一首
        if text in ("下一首", "切歌", "跳过", "下一个"):
            self.music.play_next(channel, area, user)
            return

        # 队列
        if text in ("队列", "列表", "播放列表"):
            self.music.show_queue(channel, area)
            return

        # 喜欢 / 随机
        if text in ("随机", "随机播放", "喜欢", "随便来一首"):
            self.music.play_liked(channel, area, user, 1)
            return

        # 喜欢列表
        m = re.match(r"喜欢列表\s*(\d+)?", text)
        if m:
            page = int(m.group(1)) if m.group(1) else 1
            self.music.show_liked_list(channel, area, page)
            return

        # 成员 / 在线
        if text in ("成员", "在线", "成员列表", "谁在线"):
            self._cmd_members(channel, area)
            return

        # 个人信息（基础）
        if text in ("个人信息", "我是谁", "信息"):
            self._cmd_profile(channel, area, user)
            return

        # 我的资料（详细）
        if text in ("我的资料", "我的详细资料", "我的信息"):
            self._cmd_myinfo(channel, area, user)
            return

        # 查看他人资料: @bot 查看<名字/@用户>
        for prefix in ("查看", "资料", "查询资料"):
            if text.startswith(prefix):
                target = text[len(prefix):].strip()
                if target:
                    self._cmd_whois(target, channel, area)
                else:
                    self.sender.send_message("用法: @bot 查看用户名", channel=channel, area=area)
                return

        # 角色: @bot 角色<名字/@用户>
        if text.startswith("角色"):
            target = text[2:].strip()
            if target:
                self._cmd_user_role(target, channel, area)
            else:
                self.sender.send_message("用法: @bot 角色用户名", channel=channel, area=area)
            return

        # 可分配角色: @bot 可分配角色<名字/@用户>
        for prefix in ("可分配角色", "分配角色"):
            if text.startswith(prefix):
                target = text[len(prefix):].strip()
                if target:
                    self._cmd_assignable_roles(target, channel, area)
                else:
                    self.sender.send_message("用法: @bot 可分配角色用户名", channel=channel, area=area)
                return

        # 给身份组: @bot 给身份组 <用户> <身份组名或ID>
        for prefix in ("给身份组", "添加身份组", "addrole"):
            if text.startswith(prefix):
                rest = text[len(prefix):].strip().split(None, 1)
                if len(rest) >= 2:
                    self._cmd_give_role(rest[0], rest[1], channel, area)
                else:
                    self.sender.send_message("用法: @bot 给身份组 用户 身份组名或ID", channel=channel, area=area)
                return

        # 取消身份组: @bot 取消身份组 <用户> <身份组名或ID>
        for prefix in ("取消身份组", "移除身份组", "removerole"):
            if text.startswith(prefix):
                rest = text[len(prefix):].strip().split(None, 1)
                if len(rest) >= 2:
                    self._cmd_remove_role(rest[0], rest[1], channel, area)
                else:
                    self.sender.send_message("用法: @bot 取消身份组 用户 身份组名或ID", channel=channel, area=area)
                return

        # 搜索成员: @bot 搜索<关键词>
        for prefix in ("搜索成员", "搜索", "找人"):
            if text.startswith(prefix):
                keyword = text[len(prefix):].strip()
                if keyword:
                    self._cmd_search_member(keyword, channel, area)
                else:
                    self.sender.send_message("用法: @bot 搜索用户名", channel=channel, area=area)
                return

        # 语音频道在线
        if text in ("语音", "语音频道", "语音在线", "谁在语音"):
            self._cmd_voice(channel, area)
            return

        # 进入频道: @bot 进入频道<ID>
        for prefix in ("进入频道", "进入"):
            if text.startswith(prefix):
                ch_id = text[len(prefix):].strip()
                if ch_id:
                    self._cmd_enter_channel(ch_id, channel, area)
                else:
                    self.sender.send_message("用法: @bot 进入频道<频道ID>", channel=channel, area=area)
                return

        # 每日一句
        if text in ("每日一句", "一句", "名言", "语录", "鸡汤"):
            self._cmd_daily_speech(channel, area)
            return

        # 禁言 <名字|@user> [时长]
        if text.startswith("禁言"):
            uid, dur = self._parse_mute_args(text[2:])
            if uid:
                self._cmd_mute(uid, dur, channel, area)
            else:
                self.sender.send_message("用法: @bot 禁言皇 10", channel=channel, area=area)
            return

        # 解禁 / 解除禁言
        for prefix in ("解除禁言", "解禁"):
            if text.startswith(prefix):
                uid = self._resolve_target(text[len(prefix):])
                if uid:
                    self._cmd_unmute(uid, channel, area)
                else:
                    self.sender.send_message("用法: @bot 解禁皇", channel=channel, area=area)
                return

        # 禁麦 <名字|@user> [时长]
        if text.startswith("禁麦"):
            uid, dur = self._parse_mute_args(text[2:])
            if uid:
                self._cmd_mute_mic(uid, channel, area, dur)
            else:
                self.sender.send_message("用法: @bot 禁麦皇", channel=channel, area=area)
            return

        # 解麦 / 解除禁麦
        for prefix in ("解除禁麦", "解麦"):
            if text.startswith(prefix):
                uid = self._resolve_target(text[len(prefix):])
                if uid:
                    self._cmd_unmute_mic(uid, channel, area)
                else:
                    self.sender.send_message("用法: @bot 解麦皇", channel=channel, area=area)
                return

        # 移出域 / 踢出
        for prefix in ("移出域", "踢出", "移出"):
            if text.startswith(prefix):
                uid = self._resolve_target(text[len(prefix):].strip())
                if uid:
                    self._cmd_ban(uid, channel, area)
                else:
                    self.sender.send_message("用法: @bot 移出域 用户 或 @bot 踢出 用户", channel=channel, area=area)
                return

        # 解除域内封禁 / 解封
        for prefix in ("解除域内封禁", "解封"):
            if text.startswith(prefix):
                uid = self._resolve_target(text[len(prefix):].strip())
                if uid:
                    self._cmd_unblock_in_area(uid, channel, area)
                else:
                    self.sender.send_message("用法: @bot 解封 用户（可先 @bot 封禁列表 查看）", channel=channel, area=area)
                return

        # 封禁列表
        if text.strip() in ("封禁列表", "封禁名单", "黑名单"):
            self._cmd_block_list(channel, area)
            return

        # 批量撤回 N 条
        m = re.match(r"撤回\s*(\d+)\s*条", text)
        if m:
            count = int(m.group(1))
            self._cmd_recall_multiple(count, channel, area)
            return

        # 撤回消息（单条：消息ID 或 最后）
        if text.startswith("撤回"):
            message_id = text[2:].strip()
            self._cmd_recall_message(message_id, channel, area)
            return

        # 自动撤回 开/关/秒数
        if text.startswith("自动撤回"):
            arg = text[4:].strip()
            self._cmd_auto_recall(arg, channel, area)
            return

        # 清理历史（播放历史 + 日志）
        if text in ("清理历史", "清理记录", "清除历史", "清空历史", "清理数据"):
            self._cmd_clear_history(channel, area)
            return

        # 插件管理
        if text.strip() in ("插件列表", "扩展列表", "插件"):
            self._cmd_plugin_list(channel, area)
            return
        for prefix in ("加载插件", "启用插件", "loadplugin"):
            if text.startswith(prefix):
                name = text[len(prefix):].strip()
                if name:
                    self._cmd_plugin_load(name, channel, area)
                else:
                    self.sender.send_message("用法: @bot 加载插件 <名>", channel=channel, area=area)
                return
        for prefix in ("卸载插件", "禁用插件", "unloadplugin"):
            if text.startswith(prefix):
                name = text[len(prefix):].strip()
                if name:
                    self._cmd_plugin_unload(name, channel, area)
                else:
                    self.sender.send_message("用法: @bot 卸载插件 <名>", channel=channel, area=area)
                return

        # 帮助
        if text in ("帮助", "help", "指令", "命令"):
            self._cmd_help(channel, area, user)
            return

        # 画图 / 生成图片
        for prefix in ("画", "画一个", "画一张", "生成图片", "生成", "画图"):
            if text.startswith(prefix):
                prompt = text[len(prefix):].strip()
                if prompt:
                    self._generate_image(prompt, channel, area, user)
                else:
                    self.sender.send_message("请描述要画的内容，例如: @bot 画一只可爱的猫咪", channel=channel, area=area)
                return

        # 未匹配到已知指令 → 调用 AI 回复
        reply = self.chat.ai_reply(text)
        if reply:
            self.sender.send_message(
                reply, channel=channel, area=area,
                auto_recall=self._skip_auto_recall("ai_chat"),
            )
        else:
            self.sender.send_message("我没听懂，输入 @bot 帮助 查看指令", channel=channel, area=area)

    # ------------------------------------------------------------------
    # 禁言 / 禁麦
    # ------------------------------------------------------------------

    def _resolve_target(self, text: str) -> Optional[str]:
        """从 @mention、UID 或用户名中解析目标用户 UID。"""
        text = text.strip()
        if not text:
            return None
        m = re.search(r"\(met\)(\w+)\(met\)", text)
        if m:
            return m.group(1)
        token = text.split()[0]
        if re.fullmatch(r"[a-f0-9]{32}", token):
            return token
        from name_resolver import get_resolver
        return get_resolver().find_uid_by_name(text.split()[0])

    def _parse_mute_args(self, text: str) -> tuple:
        """解析禁言参数，返回 (uid, duration)。支持: 名字 [时长]、@user [时长]、UID [时长]"""
        text = text.strip()
        m = re.match(r"\(met\)(\w+)\(met\)\s*(\d+)?", text)
        if m:
            return m.group(1), int(m.group(2)) if m.group(2) else 10

        parts = text.rsplit(None, 1)
        if len(parts) == 2 and parts[1].isdigit():
            name_part, dur = parts[0], int(parts[1])
        else:
            name_part, dur = text, 10

        uid = self._resolve_target(name_part)
        return uid, dur

    def _cmd_mute(self, uid: str, duration: int, channel: str, area: str):
        """执行禁言。"""
        from name_resolver import NameResolver
        name = NameResolver().user(uid) or uid[:8]

        result = self.sender.mute_user(uid, area=area, duration=duration)
        if "error" in result:
            self.sender.send_message(f"[x] 禁言 {name} 失败: {result['error']}", channel=channel, area=area)
        else:
            self.sender.send_message(f"[ok] {result.get('message', f'已禁言 {name}')}", channel=channel, area=area)

    def _cmd_unmute(self, uid: str, channel: str, area: str):
        """执行解除禁言。"""
        from name_resolver import NameResolver
        name = NameResolver().user(uid) or uid[:8]

        result = self.sender.unmute_user(uid, area=area)
        if "error" in result:
            self.sender.send_message(f"[x] 解除禁言 {name} 失败: {result['error']}", channel=channel, area=area)
        else:
            self.sender.send_message(f"[ok] {result.get('message', f'已解除 {name} 的禁言')}", channel=channel, area=area)

    def _cmd_mute_mic(self, uid: str, channel: str, area: str, duration: int = 10):
        """执行禁麦。"""
        from name_resolver import NameResolver
        name = NameResolver().user(uid) or uid[:8]

        result = self.sender.mute_mic(uid, area=area, duration=duration)
        if "error" in result:
            self.sender.send_message(f"[x] 禁麦 {name} 失败: {result['error']}", channel=channel, area=area)
        else:
            self.sender.send_message(f"[ok] {result.get('message', f'已禁麦 {name}')}", channel=channel, area=area)

    def _cmd_unmute_mic(self, uid: str, channel: str, area: str):
        """执行解除禁麦。"""
        from name_resolver import NameResolver
        name = NameResolver().user(uid) or uid[:8]

        result = self.sender.unmute_mic(uid, area=area)
        if "error" in result:
            self.sender.send_message(f"[x] 解除禁麦 {name} 失败: {result['error']}", channel=channel, area=area)
        else:
            self.sender.send_message(f"[ok] {result.get('message', f'已解除 {name} 的禁麦')}", channel=channel, area=area)

    def _cmd_ban(self, uid: str, channel: str, area: str):
        """将用户移出当前域（踢出域）。"""
        from name_resolver import NameResolver
        name = NameResolver().user(uid) or uid[:8]

        result = self.sender.remove_from_area(uid, area=area)
        if "error" in result:
            self.sender.send_message(f"[x] 移出域 {name} 失败: {result['error']}", channel=channel, area=area)
        else:
            self.sender.send_message(f"[ok] {result.get('message', f'已移出域 {name}')}", channel=channel, area=area)

    def _cmd_unblock_in_area(self, uid: str, channel: str, area: str):
        """解除域内封禁（从域封禁列表移除）。"""
        from name_resolver import NameResolver
        name = NameResolver().user(uid) or uid[:8]

        result = self.sender.unblock_user_in_area(uid, area=area)
        if "error" in result:
            self.sender.send_message(f"[x] 解除域内封禁 {name} 失败: {result['error']}", channel=channel, area=area)
        else:
            self.sender.send_message(f"[ok] {result.get('message', f'已解除 {name} 的域内封禁')}", channel=channel, area=area)

    def _cmd_block_list(self, channel: str, area: str):
        """展示当前域封禁列表（解除封禁前可先查看）。"""
        from name_resolver import get_resolver
        resolver = get_resolver()

        data = self.sender.get_area_blocks(area=area)
        if "error" in data:
            self.sender.send_message(f"获取域封禁列表失败: {data['error']}", channel=channel, area=area)
            return

        blocks = data.get("blocks", [])
        area_name = resolver.area(area)
        if not blocks:
            self.sender.send_message(f"{area_name} 当前无封禁用户。", channel=channel, area=area)
            return

        lines = [f"{area_name} - 封禁列表（共 {len(blocks)} 人）", "---"]
        for i, item in enumerate(blocks, 1):
            uid = item.get("uid") or item.get("person") or item.get("target") or str(item)
            if isinstance(uid, dict):
                uid = uid.get("uid") or uid.get("person") or ""
            name = resolver.user(uid) if isinstance(uid, str) else ""
            disp = f"{name} ({uid[:8]}…)" if name else uid[:16] + "…"
            lines.append(f"{i}. {disp}")
        lines.append("--- 使用 /unblock 用户 或 @bot 解封 用户 解除封禁")
        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    # ------------------------------------------------------------------
    # 域成员列表
    # ------------------------------------------------------------------

    def _cmd_members(self, channel: str, area: str):
        """查询域内成员并展示在线状态"""
        from name_resolver import get_resolver
        resolver = get_resolver()

        # 分页拉取，避免仅统计到第一页成员（默认接口分页）。
        members = []
        seen_uids: set[str] = set()
        page_size = 100
        max_fetch = 500
        for start in range(0, max_fetch, page_size):
            data = self.sender.get_area_members(
                area=area,
                offset_start=start,
                offset_end=start + page_size - 1,
                quiet=True,
            )
            if "error" in data:
                self.sender.send_message(f"查询成员列表失败: {data['error']}", channel=channel, area=area)
                return
            batch = data.get("members", []) or []
            for m in batch:
                uid = (m.get("uid") or "").strip()
                if not uid or uid in seen_uids:
                    continue
                seen_uids.add(uid)
                members.append(m)
            if len(batch) < page_size:
                break

        online = [m for m in members if m.get("online") == 1]
        offline = [m for m in members if m.get("online") != 1]

        area_name = resolver.area(area)
        lines = [
            f"{area_name} - 成员列表",
            f"总计 {len(members)} 人 | 在线 {len(online)} 人",
            "---",
        ]

        if online:
            lines.append("在线:")
            show_limit = 50
            for m in online[:show_limit]:
                name = resolver.user(m.get("uid", ""))
                state = m.get("playingState", "")
                suffix = f" ({state})" if state else ""
                lines.append(f"  {name}{suffix}")
            if len(online) > show_limit:
                lines.append(f"  ... 还有 {len(online) - show_limit} 人在线")

        if offline:
            lines.append(f"离线: {len(offline)} 人")

        if len(members) >= max_fetch:
            lines.append(f"提示: 仅展示前 {max_fetch} 名成员统计")

        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    # ------------------------------------------------------------------
    # 个人信息查询
    # ------------------------------------------------------------------

    def _cmd_profile(self, channel: str, area: str, user: str):
        """查询用户详细信息（通过 personInfos 接口，可查任意用户）"""
        data = self.sender.get_person_detail(uid=user)
        if "error" in data:
            self.sender.send_message(f"查询个人信息失败: {data['error']}", channel=channel, area=area)
            return

        name = data.get("name", "未知")

        lines = [
            f"个人信息 - {name}",
            "---",
            f"  UID: {user}",
        ]

        # 以下字段可能存在也可能不存在，按实际返回动态展示
        if "online" in data:
            lines.append(f"  状态: {'在线' if data['online'] else '离线'}")

        if data.get("introduction"):
            lines.append(f"  简介: {data['introduction']}")

        if data.get("ipAddress"):
            lines.append(f"  IP属地: {data['ipAddress']}")

        if data.get("personType"):
            lines.append(f"  类型: {data['personType']}")

        if data.get("playingState"):
            lines.append(f"  正在玩: {data['playingState']}")

        if data.get("avatar"):
            lines.append(f"  头像: {data['avatar']}")

        vip_end = data.get("personVIPEndTime", 0)
        if vip_end and vip_end > 0:
            import datetime
            vip_end_str = datetime.datetime.fromtimestamp(vip_end / 1000).strftime("%Y-%m-%d")
            lines.append(f"  VIP到期: {vip_end_str}")

        badges = data.get("badges", [])
        if badges:
            lines.append(f"  徽章: {len(badges)} 个")

        # 如果返回数据很少，补充提示
        if len(lines) <= 3:
            lines.append("  （该接口返回信息有限）")

        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    # ------------------------------------------------------------------
    # 自身详细资料
    # ------------------------------------------------------------------

    def _cmd_myinfo(self, channel: str, area: str, user: str):
        """查询发起指令用户的完整详细资料"""
        data = self.sender.get_person_detail_full(user)
        if "error" in data:
            self.sender.send_message(f"查询资料失败: {data['error']}", channel=channel, area=area)
            return

        person = data.get("person", data)
        name = person.get("name", "未知")
        lines = [f"我的详细资料 - {name}", "---"]

        for label, key in [
            ("UID", "uid"), ("简介", "introduction"), ("IP属地", "ipAddress"),
            ("类型", "personType"), ("性别", "sex"),
        ]:
            val = person.get(key)
            if val:
                lines.append(f"  {label}: {val}")

        if person.get("online") is not None:
            lines.append(f"  状态: {'在线' if person['online'] else '离线'}")

        vip_end = person.get("personVIPEndTime", 0)
        if vip_end and vip_end > 0:
            import datetime
            lines.append(f"  VIP到期: {datetime.datetime.fromtimestamp(vip_end / 1000).strftime('%Y-%m-%d')}")

        badges = person.get("badges", [])
        if badges:
            badge_names = [b.get("name", "") for b in badges if b.get("name")]
            lines.append(f"  徽章({len(badges)}): {', '.join(badge_names[:10])}")

        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    # ------------------------------------------------------------------
    # 查看他人详细资料
    # ------------------------------------------------------------------

    def _cmd_whois(self, target: str, channel: str, area: str):
        """查看他人完整详细资料"""
        uid = self._resolve_target(target)
        if not uid:
            self.sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        data = self.sender.get_person_detail_full(uid)
        if "error" in data:
            self.sender.send_message(f"查询资料失败: {data['error']}", channel=channel, area=area)
            return

        person = data.get("person", data)
        name = person.get("name", uid[:8])
        lines = [f"用户资料 - {name}", "---"]

        for label, key in [
            ("UID", "uid"), ("简介", "introduction"), ("IP属地", "ipAddress"),
            ("类型", "personType"), ("性别", "sex"),
        ]:
            val = person.get(key)
            if val:
                lines.append(f"  {label}: {val}")

        if person.get("online") is not None:
            lines.append(f"  状态: {'在线' if person['online'] else '离线'}")

        if person.get("playingState"):
            lines.append(f"  正在玩: {person['playingState']}")

        vip_end = person.get("personVIPEndTime", 0)
        if vip_end and vip_end > 0:
            import datetime
            lines.append(f"  VIP到期: {datetime.datetime.fromtimestamp(vip_end / 1000).strftime('%Y-%m-%d')}")

        badges = person.get("badges", [])
        if badges:
            badge_names = [b.get("name", "") for b in badges if b.get("name")]
            lines.append(f"  徽章({len(badges)}): {', '.join(badge_names[:10])}")

        if person.get("avatar"):
            lines.append(f"  头像: {person['avatar']}")

        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    # ------------------------------------------------------------------
    # 用户在域内的角色 / 禁言状态
    # ------------------------------------------------------------------

    def _cmd_user_role(self, target: str, channel: str, area: str):
        """查看指定用户在域内的角色和禁言/禁麦状态"""
        uid = self._resolve_target(target)
        if not uid:
            self.sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        from name_resolver import get_resolver
        resolver = get_resolver()
        name = resolver.user(uid)

        data = self.sender.get_user_area_detail(uid, area=area)
        if "error" in data:
            self.sender.send_message(f"查询角色失败: {data['error']}", channel=channel, area=area)
            return

        area_name = resolver.area(area)
        lines = [f"{name} 在 {area_name} 的角色信息", "---"]

        roles = data.get("list", [])
        if roles:
            lines.append("角色列表:")
            for r in roles:
                lines.append(f"  • {r.get('name', '未知')} (ID={r.get('roleID', '?')})")
        else:
            lines.append("  无角色")

        text_mute = data.get("disableTextTo", 0)
        voice_mute = data.get("disableVoiceTo", 0)
        if text_mute and text_mute > 0:
            import datetime
            end = datetime.datetime.fromtimestamp(text_mute / 1000).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  禁言至: {end}")
        else:
            lines.append("  禁言: 无")

        if voice_mute and voice_mute > 0:
            import datetime
            end = datetime.datetime.fromtimestamp(voice_mute / 1000).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  禁麦至: {end}")
        else:
            lines.append("  禁麦: 无")

        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    # ------------------------------------------------------------------
    # 可分配的角色列表
    # ------------------------------------------------------------------

    def _cmd_assignable_roles(self, target: str, channel: str, area: str):
        """查看可以分配给目标用户的角色列表"""
        uid = self._resolve_target(target)
        if not uid:
            self.sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        from name_resolver import get_resolver
        name = get_resolver().user(uid)

        roles = self.sender.get_assignable_roles(uid, area=area)
        if not roles:
            self.sender.send_message(f"没有可分配给 {name} 的角色", channel=channel, area=area)
            return

        lines = [f"可分配给 {name} 的角色", "---"]
        for r in roles:
            owned = " [已拥有]" if r.get("owned") else ""
            lines.append(f"  • {r.get('name', '未知')} (ID={r.get('roleID', '?')}){owned}")

        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    def _cmd_give_role(self, target: str, role_arg: str, channel: str, area: str):
        """给目标用户添加身份组。role_arg 为身份组名或 roleID。"""
        from name_resolver import get_resolver
        uid = self._resolve_target(target)
        if not uid:
            self.sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return
        name = get_resolver().user(uid)
        roles = self.sender.get_assignable_roles(uid, area=area)
        if not roles:
            self.sender.send_message(f"没有可分配给 {name} 的身份组", channel=channel, area=area)
            return
        role_id = None
        role_arg_stripped = role_arg.strip()
        for r in roles:
            rid = r.get("roleID")
            rname = (r.get("name") or "").strip()
            if str(rid) == role_arg_stripped or rname == role_arg_stripped:
                role_id = rid
                break
        if role_id is None:
            self.sender.send_message(
                f"未找到身份组 \"{role_arg}\"。可用 /roles {target} 查看可分配列表",
                channel=channel, area=area,
            )
            return
        result = self.sender.edit_user_role(uid, role_id, add=True, area=area)
        if "error" in result:
            self.sender.send_message(f"[x] 给 {name} 添加身份组失败: {result['error']}", channel=channel, area=area)
        else:
            self.sender.send_message(f"[ok] {result.get('message', f'已给 {name} 添加身份组')}", channel=channel, area=area)

    def _cmd_remove_role(self, target: str, role_arg: str, channel: str, area: str):
        """取消目标用户的指定身份组。role_arg 为身份组名或 roleID。"""
        from name_resolver import get_resolver
        uid = self._resolve_target(target)
        if not uid:
            self.sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return
        name = get_resolver().user(uid)
        detail = self.sender.get_user_area_detail(uid, area=area)
        if "error" in detail:
            self.sender.send_message(f"获取用户角色失败: {detail['error']}", channel=channel, area=area)
            return
        role_list = detail.get("list") or []
        if not role_list:
            self.sender.send_message(f"{name} 当前没有可取消的身份组", channel=channel, area=area)
            return
        role_id = None
        role_arg_stripped = role_arg.strip()
        for r in role_list:
            rid = r.get("roleID")
            rname = (r.get("name") or "").strip()
            if rid is not None and (str(rid) == role_arg_stripped or rname == role_arg_stripped):
                role_id = rid
                break
        if role_id is None:
            self.sender.send_message(
                f"未找到身份组 \"{role_arg}\"。可用 /role {target} 查看其当前角色",
                channel=channel, area=area,
            )
            return
        result = self.sender.edit_user_role(uid, role_id, add=False, area=area)
        if "error" in result:
            self.sender.send_message(f"[x] 取消 {name} 身份组失败: {result['error']}", channel=channel, area=area)
        else:
            self.sender.send_message(f"[ok] {result.get('message', f'已取消 {name} 的该身份组')}", channel=channel, area=area)

    # ------------------------------------------------------------------
    # 搜索域成员
    # ------------------------------------------------------------------

    def _cmd_search_member(self, keyword: str, channel: str, area: str):
        """搜索域内成员"""
        from name_resolver import get_resolver
        resolver = get_resolver()

        members = self.sender.search_area_members(area=area, keyword=keyword)
        if not members:
            self.sender.send_message(f"未找到匹配 \"{keyword}\" 的成员", channel=channel, area=area)
            return

        lines = [f"搜索 \"{keyword}\" - 找到 {len(members)} 人", "---"]
        for m in members[:20]:
            uid = m.get("uid", "")
            name = resolver.user(uid)
            roles_info = m.get("roleInfos", [])
            role_names = [r.get("name", "") for r in roles_info if r.get("name")]
            role_str = f" [{', '.join(role_names)}]" if role_names else ""
            enter_time = m.get("enterTime", 0)
            time_str = ""
            if enter_time:
                import datetime
                time_str = f" 加入于 {datetime.datetime.fromtimestamp(enter_time / 1000).strftime('%Y-%m-%d')}"
            lines.append(f"  {name}{role_str}{time_str}")

        if len(members) > 20:
            lines.append(f"  ... 还有 {len(members) - 20} 人")

        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    # ------------------------------------------------------------------
    # 各语音频道在线成员
    # ------------------------------------------------------------------

    def _cmd_voice(self, channel: str, area: str):
        """查看各语音频道的在线成员"""
        from name_resolver import get_resolver
        resolver = get_resolver()

        channel_members = self.sender.get_voice_channel_members(area=area)
        if not channel_members:
            self.sender.send_message("当前没有语音频道在线成员", channel=channel, area=area)
            return

        area_name = resolver.area(area)
        lines = [f"{area_name} - 语音频道在线", "---"]

        total_online = 0
        for ch_id, members in channel_members.items():
            if not members:
                continue
            ch_name = resolver.channel(ch_id)
            lines.append(f"{ch_name} ({len(members)}人):")
            for m in members:
                if isinstance(m, dict):
                    uid = m.get("uid", m.get("id", ""))
                    is_bot = m.get("isBot", False)
                    name = resolver.user(uid)
                    suffix = " [Bot]" if is_bot else ""
                    lines.append(f"  • {name}{suffix}")
                else:
                    lines.append(f"  • {resolver.user(str(m))}")
            total_online += len(members)

        if total_online == 0:
            self.sender.send_message("当前没有语音频道在线成员", channel=channel, area=area)
            return

        lines.insert(1, f"共 {total_online} 人在线")
        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    # ------------------------------------------------------------------
    # 进入频道
    # ------------------------------------------------------------------

    def _cmd_enter_channel(self, ch_id: str, channel: str, area: str):
        """进入指定频道"""
        from name_resolver import get_resolver
        resolver = get_resolver()

        ch_name = resolver.channel(ch_id)
        data = self.sender.enter_channel(channel=ch_id, area=area)
        if "error" in data:
            self.sender.send_message(f"进入频道失败: {data['error']}", channel=channel, area=area)
            return

        lines = [f"已进入频道: {ch_name}", "---"]

        for label, key in [
            ("语音质量", "voiceQuality"), ("语音延迟", "voiceDelay"),
            ("角色排序", "roleSort"),
        ]:
            val = data.get(key)
            if val is not None:
                lines.append(f"  {label}: {val}")

        text_mute = data.get("disableTextTo", 0)
        voice_mute = data.get("disableVoiceTo", 0)
        if text_mute and text_mute > 0:
            lines.append("  文字禁言: 是")
        if voice_mute and voice_mute > 0:
            lines.append("  语音禁言: 是")

        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    # ------------------------------------------------------------------
    # 每日一句
    # ------------------------------------------------------------------

    def _cmd_daily_speech(self, channel: str, area: str):
        """获取并展示每日一句名言"""
        data = self.sender.get_daily_speech()
        if "error" in data:
            self.sender.send_message(f"获取每日一句失败: {data['error']}", channel=channel, area=area)
            return

        words = data.get("words", "")
        author = data.get("author", "")

        if words:
            text = f"「{words}」"
            if author:
                text += f"\n—— {author}"
        else:
            text = "暂无内容"

        self.sender.send_message(text, channel=channel, area=area)

    # ------------------------------------------------------------------
    # AI 图片生成
    # ------------------------------------------------------------------

    def _generate_image(self, prompt: str, channel: str, area: str, user: str):
        """调用 AI 生成图片并发送到频道"""
        from name_resolver import NameResolver
        names = NameResolver()
        user_name = names.user(user) if user else "未知用户"

        self.sender.send_message(f"[paint] {user_name} 请求生成图片，正在绘制中...", channel=channel, area=area)

        image_url = self.chat.generate_image(prompt)
        if not image_url:
            self.sender.send_message("图片生成失败，请稍后再试", channel=channel, area=area)
            return

        # 上传到 Oopz
        upload_result = self.sender.upload_file_from_url(image_url)
        if upload_result.get("code") != "success":
            self.sender.send_message("图片上传失败，请稍后再试", channel=channel, area=area)
            return

        att = upload_result["data"]
        text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n{user_name} 生成的图片:\n描述: {prompt}"
        self.sender.send_message(
            text=text, attachments=[att], channel=channel, area=area,
            auto_recall=self._skip_auto_recall("ai_image"),
        )

    # ------------------------------------------------------------------
    # / 命令分发
    # ------------------------------------------------------------------

    def _dispatch_command(self, content: str, channel: str, area: str, user: str):
        parts = content.split()
        if not parts:
            return
        command = parts[0].lower()
        subcommand = parts[1].lower() if len(parts) > 1 else None
        arg = " ".join(parts[2:]) if len(parts) > 2 else None
        if self._plugin_registry.try_dispatch_slash(command, subcommand, arg, channel, area, user, self):
            return

        # 管理员：/plugins 插件列表、/loadplugin <名>、/unloadplugin <名>
        if self._is_admin(user):
            if command == "/plugins":
                self._cmd_plugin_list(channel, area)
                return
            if command == "/loadplugin":
                raw_name = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
                if raw_name:
                    self._cmd_plugin_load(raw_name, channel, area)
                else:
                    self.sender.send_message("用法: /loadplugin <名>", channel=channel, area=area)
                return
            if command == "/unloadplugin":
                raw_name = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
                if raw_name:
                    self._cmd_plugin_unload(raw_name, channel, area)
                else:
                    self.sender.send_message("用法: /unloadplugin <名>", channel=channel, area=area)
                return

        # /help
        if command == "/help":
            self._cmd_help(channel, area, user)
            return

        # /bf <歌名> 或 /play <歌名>
        if command in ("/bf", "/play"):
            keyword = " ".join(parts[1:]) if len(parts) > 1 else None
            if keyword:
                self.music.play_netease(keyword, channel, area, user)
            else:
                self.sender.send_message("用法: /bf 歌曲名", channel=channel, area=area)
            return

        # /yun play <歌名>
        if command == "/yun" and subcommand == "play":
            if arg:
                self.music.play_netease(arg, channel, area, user)
            else:
                self.sender.send_message("用法: /yun play 歌曲名", channel=channel, area=area)
            return

        # /next
        if command == "/next":
            self.music.play_next(channel, area, user)
            return

        # /queue
        if command == "/queue":
            self.music.show_queue(channel, area)
            return

        # /st 或 /stop
        if command in ("/st", "/stop"):
            self.music.stop_play(channel, area)
            return

        # /like 系列命令
        if command == "/like":
            # /like list [页码]
            if subcommand == "list":
                page = 1
                if arg:
                    try:
                        page = int(arg)
                    except ValueError:
                        pass
                self.music.show_liked_list(channel, area, page)
                return

            # /like play <编号>
            if subcommand == "play":
                if arg:
                    try:
                        index = int(arg)
                        self.music.play_liked_by_index(index, channel, area, user)
                    except ValueError:
                        self.sender.send_message("用法: /like play <编号>", channel=channel, area=area)
                else:
                    self.sender.send_message("用法: /like play <编号>\n先用 /like list 查看列表", channel=channel, area=area)
                return

            # /like [数量] - 随机播放
            count = 1
            if subcommand:
                try:
                    count = int(subcommand)
                    count = max(1, min(count, 20))
                except ValueError:
                    self.sender.send_message(
                        "用法:\n  /like         随机播放1首\n  /like <数量>   随机播放多首\n"
                        "  /like list    查看喜欢列表\n  /like play <编号>  播放指定歌曲",
                        channel=channel, area=area,
                    )
                    return
            self.music.play_liked(channel, area, user, count)
            return

        # /members - 查看域成员在线状态
        if command in ("/members", "/online"):
            self._cmd_members(channel, area)
            return

        # /me - 查看个人信息
        if command == "/me":
            self._cmd_profile(channel, area, user)
            return

        # /myinfo - 自身详细资料
        if command == "/myinfo":
            self._cmd_myinfo(channel, area, user)
            return

        # /whois <名字/uid> - 查看他人详细资料
        if command == "/whois":
            target = " ".join(parts[1:]) if len(parts) > 1 else None
            if target:
                self._cmd_whois(target, channel, area)
            else:
                self.sender.send_message("用法: /whois 用户名", channel=channel, area=area)
            return

        # /role <名字/uid> - 查看用户在域内角色/禁言状态
        if command == "/role":
            target = " ".join(parts[1:]) if len(parts) > 1 else None
            if target:
                self._cmd_user_role(target, channel, area)
            else:
                self.sender.send_message("用法: /role 用户名", channel=channel, area=area)
            return

        # /roles <名字/uid> - 可分配的角色列表
        if command == "/roles":
            target = " ".join(parts[1:]) if len(parts) > 1 else None
            if target:
                self._cmd_assignable_roles(target, channel, area)
            else:
                self.sender.send_message("用法: /roles 用户名", channel=channel, area=area)
            return

        # /addrole <用户> <身份组名或ID> - 给身份组
        if command == "/addrole":
            if len(parts) >= 3:
                role_arg = " ".join(parts[2:]).strip()
                if role_arg:
                    self._cmd_give_role(parts[1], role_arg, channel, area)
                else:
                    self.sender.send_message("用法: /addrole 用户 身份组名或ID", channel=channel, area=area)
            else:
                self.sender.send_message("用法: /addrole 用户 身份组名或ID\n示例: /addrole 皇 管理员", channel=channel, area=area)
            return

        # /removerole <用户> <身份组名或ID> - 取消身份组
        if command == "/removerole":
            if len(parts) >= 3:
                role_arg = " ".join(parts[2:]).strip()
                if role_arg:
                    self._cmd_remove_role(parts[1], role_arg, channel, area)
                else:
                    self.sender.send_message("用法: /removerole 用户 身份组名或ID", channel=channel, area=area)
            else:
                self.sender.send_message("用法: /removerole 用户 身份组名或ID\n示例: /removerole 皇 管理员", channel=channel, area=area)
            return

        # /search <关键词> - 搜索域成员
        if command == "/search":
            keyword = " ".join(parts[1:]) if len(parts) > 1 else None
            if keyword:
                self._cmd_search_member(keyword, channel, area)
            else:
                self.sender.send_message("用法: /search 关键词", channel=channel, area=area)
            return

        # /voice - 语音频道在线成员
        if command == "/voice":
            self._cmd_voice(channel, area)
            return

        # /enter <频道ID> - 进入频道
        if command == "/enter":
            ch_id = " ".join(parts[1:]) if len(parts) > 1 else None
            if ch_id:
                self._cmd_enter_channel(ch_id, channel, area)
            else:
                self.sender.send_message("用法: /enter 频道ID", channel=channel, area=area)
            return

        # /daily - 每日一句
        if command in ("/daily", "/quote"):
            self._cmd_daily_speech(channel, area)
            return

        # /禁言 <名字> [时长] 或 /mute
        if command in ("/禁言", "/mute"):
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid, dur = self._parse_mute_args(raw)
            if uid:
                self._cmd_mute(uid, dur, channel, area)
            else:
                self.sender.send_message("用法: /禁言 皇 10", channel=channel, area=area)
            return

        # /解禁 <名字> 或 /unmute
        if command in ("/解禁", "/unmute"):
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid = self._resolve_target(raw)
            if uid:
                self._cmd_unmute(uid, channel, area)
            else:
                self.sender.send_message("用法: /解禁 皇", channel=channel, area=area)
            return

        # /禁麦 <名字> [时长] 或 /mutemic
        if command in ("/禁麦", "/mutemic"):
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid, dur = self._parse_mute_args(raw)
            if uid:
                self._cmd_mute_mic(uid, channel, area, dur)
            else:
                self.sender.send_message("用法: /禁麦 皇", channel=channel, area=area)
            return

        # /解麦 <名字> 或 /unmutemic
        if command in ("/解麦", "/unmutemic"):
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid = self._resolve_target(raw)
            if uid:
                self._cmd_unmute_mic(uid, channel, area)
            else:
                self.sender.send_message("用法: /解麦 皇", channel=channel, area=area)
            return

        # /ban <名字> - 移出域（踢出）
        if command == "/ban":
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid = self._resolve_target(raw)
            if uid:
                self._cmd_ban(uid, channel, area)
            else:
                self.sender.send_message("用法: /ban 用户", channel=channel, area=area)
            return

        # /unblock <名字> - 解除域内封禁（从域封禁列表移除）
        if command == "/unblock":
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid = self._resolve_target(raw)
            if uid:
                self._cmd_unblock_in_area(uid, channel, area)
            else:
                self.sender.send_message("用法: /unblock 用户（可先 /blocklist 查看封禁列表）", channel=channel, area=area)
            return

        # /blocklist - 域封禁列表
        if command == "/blocklist":
            self._cmd_block_list(channel, area)
            return

        # /autorecall - 自动撤回开关
        if command == "/autorecall":
            arg = " ".join(parts[1:]) if len(parts) > 1 else ""
            self._cmd_auto_recall(arg, channel, area)
            return

        # /clear history - 清理播放历史记录
        if command == "/clear" and subcommand == "history":
            self._cmd_clear_history(channel, area)
            return

        # /recall <messageId> - 撤回消息
        if command == "/recall":
            arg = " ".join(parts[1:]) if len(parts) > 1 else None
            # 检查是否是数字（撤回多条）
            if arg and arg.isdigit():
                self._cmd_recall_multiple(int(arg), channel, area)
            else:
                self._cmd_recall_message(arg, channel, area)
            return

        # 未知命令
        self.sender.send_message(f"未知命令: {command}\n输入 /help 查看帮助", channel=channel, area=area)

    def _resolve_timestamp(self, message_id: str, channel: str, area: str) -> Optional[str]:
        """从内存记录或远程 API 查找消息的 timestamp"""
        for msg in reversed(self._recent_messages):
            if msg.get("messageId") == message_id and msg.get("timestamp"):
                return msg["timestamp"]
        return self.sender.find_message_timestamp(message_id, area=area, channel=channel)

    def _cmd_recall_message(self, message_id: Optional[str], channel: str, area: str):
        """撤回指定消息"""
        content_preview = ""
        recent = None

        if not message_id or message_id.lower() in ("last", "最后", "最后一条", "上一条"):
            if not self._recent_messages:
                self.sender.send_message(
                    "[x] 没有可撤回的消息记录",
                    channel=channel, area=area,
                )
                return

            for msg in reversed(self._recent_messages):
                if msg.get("channel") == channel and msg.get("area") == area:
                    recent = msg
                    break

            if not recent:
                self.sender.send_message(
                    "[x] 在当前频道没有找到可撤回的消息\n"
                    "请使用: /recall <消息ID> 或 @bot 撤回 <消息ID>",
                    channel=channel, area=area,
                )
                return

            message_id = recent["messageId"]
            content_preview = recent.get("content", "")[:30]

        timestamp = self._resolve_timestamp(message_id, channel, area)

        result = self.sender.recall_message(
            message_id, area=area, channel=channel, timestamp=timestamp,
        )
        if "error" in result:
            err = result["error"]
            hint = ""
            if "record not found" in (err or "").lower() or "服务异常" in (err or ""):
                hint = "\n提示: 该消息可能已撤回/过期，或消息 ID 无效（请用长按消息复制得到的完整 ID）。"
            mid_preview = (message_id[:24] + "…") if len(str(message_id)) > 24 else str(message_id)
            self.sender.send_message(
                f"[x] 撤回失败: {err}\n消息ID: {mid_preview}{hint}",
                channel=channel, area=area,
            )
        else:
            preview = f" ({content_preview}...)" if content_preview else ""
            self.sender.send_message(
                f"[ok] 消息已撤回{preview}\n消息ID: {message_id[:20]}...",
                channel=channel, area=area,
            )

    def _cmd_recall_multiple(self, count: int, channel: str, area: str):
        """批量撤回多条消息（优先用内存记录，不足时从 API 拉取）"""
        if count <= 0:
            self.sender.send_message("[x] 撤回数量必须大于0", channel=channel, area=area)
            return

        if count > 100:
            self.sender.send_message("[x] 最多只能一次撤回100条消息", channel=channel, area=area)
            return

        # 内存中当前频道的消息
        channel_messages = [
            msg for msg in self._recent_messages
            if msg.get("channel") == channel and msg.get("area") == area
        ]

        # 内存不够时，从 API 拉取频道最近消息补充
        if len(channel_messages) < count:
            remote_msgs = self.sender.get_channel_messages(area=area, channel=channel, size=count)
            remote_map = {m["messageId"]: m for m in remote_msgs}
            known_ids = {m["messageId"] for m in channel_messages}
            for rm in remote_msgs:
                if rm["messageId"] not in known_ids:
                    channel_messages.append({
                        "messageId": rm["messageId"],
                        "channel": rm.get("channel", channel),
                        "area": rm.get("area", area),
                        "content": (rm.get("content") or "")[:50],
                        "timestamp": rm.get("timestamp", ""),
                    })
            channel_messages.sort(key=lambda m: m.get("timestamp") or "0")

        if not channel_messages:
            self.sender.send_message("[x] 在当前频道没有找到可撤回的消息", channel=channel, area=area)
            return

        to_recall = channel_messages[-count:]
        success_count = 0
        fail_count = 0

        self.sender.send_message(f"[sync] 正在撤回 {len(to_recall)} 条消息...", channel=channel, area=area)

        import time
        for msg in reversed(to_recall):
            ts = msg.get("timestamp") or self._resolve_timestamp(msg["messageId"], channel, area)
            result = self.sender.recall_message(
                msg["messageId"], area=area, channel=channel, timestamp=ts,
            )
            if "error" not in result:
                success_count += 1
            else:
                fail_count += 1
            time.sleep(0.3)

        result_msg = f"[ok] 批量撤回完成:\n成功: {success_count} 条"
        if fail_count > 0:
            result_msg += f"\n失败: {fail_count} 条"
        self.sender.send_message(result_msg, channel=channel, area=area)

    def _cmd_auto_recall(self, arg: str, channel: str, area: str):
        """管理自动撤回功能：开/关/设置延迟/排除命令"""
        arg = arg.strip()

        # 无参数 → 显示当前状态
        if not arg:
            enabled = AUTO_RECALL_CONFIG.get("enabled", False)
            delay = AUTO_RECALL_CONFIG.get("delay", 30)
            exclude = AUTO_RECALL_CONFIG.get("exclude_commands", [])
            status = "开启" if enabled else "关闭"
            exclude_names = {
                "ai_chat": "AI 聊天",
                "ai_image": "AI 生成图片",
            }
            exclude_display = ", ".join(exclude_names.get(e, e) for e in exclude) or "无"
            self.sender.send_message(
                f"自动撤回状态\n---\n"
                f"  状态: {status}\n"
                f"  延迟: {delay} 秒\n"
                f"  排除: {exclude_display}\n"
                f"---\n"
                f"用法:\n"
                f"  自动撤回 开 [秒数]  开启（可选设置延迟）\n"
                f"  自动撤回 关        关闭\n"
                f"  自动撤回 排除 <类型>  添加排除\n"
                f"  自动撤回 取消排除 <类型>  移除排除\n"
                f"  类型: ai_chat / ai_image",
                channel=channel, area=area,
            )
            return

        # 开 / 开 <秒数>
        if arg.startswith("开"):
            rest = arg[1:].strip()
            if rest and rest.isdigit():
                AUTO_RECALL_CONFIG["delay"] = int(rest)
            AUTO_RECALL_CONFIG["enabled"] = True
            delay = AUTO_RECALL_CONFIG["delay"]
            self.sender.send_message(
                f"[ok] 自动撤回已开启，延迟 {delay} 秒",
                channel=channel, area=area,
            )
            return

        # 关
        if arg in ("关", "关闭", "off"):
            AUTO_RECALL_CONFIG["enabled"] = False
            self.sender.send_message("[ok] 自动撤回已关闭", channel=channel, area=area)
            return

        # on / on <seconds>
        if arg.startswith("on"):
            rest = arg[2:].strip()
            if rest and rest.isdigit():
                AUTO_RECALL_CONFIG["delay"] = int(rest)
            AUTO_RECALL_CONFIG["enabled"] = True
            delay = AUTO_RECALL_CONFIG["delay"]
            self.sender.send_message(
                f"[ok] 自动撤回已开启，延迟 {delay} 秒",
                channel=channel, area=area,
            )
            return

        # 纯数字 → 设置延迟秒数
        if arg.isdigit():
            seconds = int(arg)
            if seconds <= 0:
                self.sender.send_message("[x] 延迟秒数必须大于 0", channel=channel, area=area)
                return
            AUTO_RECALL_CONFIG["delay"] = seconds
            self.sender.send_message(
                f"[ok] 自动撤回延迟已设为 {seconds} 秒",
                channel=channel, area=area,
            )
            return

        # 排除 <命令类型>
        if arg.startswith("排除"):
            cmd_type = arg[2:].strip()
            if not cmd_type:
                self.sender.send_message("用法: 自动撤回 排除 ai_chat", channel=channel, area=area)
                return
            exclude = AUTO_RECALL_CONFIG.setdefault("exclude_commands", [])
            if cmd_type in exclude:
                self.sender.send_message(f"[info] {cmd_type} 已在排除列表中", channel=channel, area=area)
            else:
                exclude.append(cmd_type)
                self.sender.send_message(f"[ok] 已将 {cmd_type} 加入排除列表", channel=channel, area=area)
            return

        # 取消排除 <命令类型>
        if arg.startswith("取消排除"):
            cmd_type = arg[4:].strip()
            if not cmd_type:
                self.sender.send_message("用法: 自动撤回 取消排除 ai_chat", channel=channel, area=area)
                return
            exclude = AUTO_RECALL_CONFIG.get("exclude_commands", [])
            if cmd_type in exclude:
                exclude.remove(cmd_type)
                self.sender.send_message(f"[ok] 已将 {cmd_type} 从排除列表移除", channel=channel, area=area)
            else:
                self.sender.send_message(f"[info] {cmd_type} 不在排除列表中", channel=channel, area=area)
            return

        self.sender.send_message(
            "用法: 自动撤回 开/关/秒数/排除/取消排除",
            channel=channel, area=area,
        )

    def _cmd_clear_history(self, channel: str, area: str):
        """清理播放历史记录和日志文件"""
        from database import SongCache
        from logger_config import LOG_FILE
        import os
        
        results = []
        
        # 清理播放历史记录
        try:
            count = SongCache.clear_play_history()
            results.append(f"[ok] 播放历史记录: 已删除 {count} 条")
        except Exception as e:
            logger.error(f"清理播放历史记录失败: {e}")
            results.append("[x] 播放历史记录: 清理失败")
        
        # 清理日志文件
        try:
            log_count = 0
            if os.path.exists(LOG_FILE):
                # 统计日志行数
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    log_count = len(f.readlines())
                # 清空日志文件
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.write("")
                results.append(f"[ok] 日志文件: 已清空 ({log_count} 行)")
            else:
                results.append("[info] 日志文件: 不存在")
        except Exception as e:
            logger.error(f"清理日志文件失败: {e}")
            results.append("[x] 日志文件: 清理失败")
        
        # 清空消息历史记录
        msg_count = len(self._recent_messages)
        self._recent_messages.clear()
        results.append(f"[ok] 消息历史记录: 已清空 ({msg_count} 条)")
        
        # 发送结果
        message = "清理完成:\n" + "\n".join(results)
        self.sender.send_message(message, channel=channel, area=area)

    @staticmethod
    def _normalize_plugin_name(raw_name: str) -> Optional[str]:
        """规范化插件名，仅允许字母数字下划线，兼容传入 .py 后缀。"""
        name = (raw_name or "").strip()
        if name.endswith(".py"):
            name = name[:-3]
        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            return None
        return name

    def _cmd_plugin_list(self, channel: str, area: str):
        """展示插件状态：已加载与可加载列表。"""
        loaded = self._plugin_registry.list_all()
        discovered = discover_plugins("plugins")

        loaded_names = {item.get("name", "") for item in loaded}
        available = [name for name in discovered if name not in loaded_names]

        lines = ["插件状态", "---"]
        lines.append(f"已加载: {len(loaded)} 个")
        if loaded:
            for item in loaded:
                tag = "内置" if item.get("builtin") else "扩展"
                desc = item.get("description", "")
                suffix = f" - {desc}" if desc else ""
                lines.append(f"  {item.get('name', '')} [{tag}]{suffix}")
        else:
            lines.append("  （无）")

        lines.append("")
        lines.append(f"可加载: {len(available)} 个")
        if available:
            lines.append("  " + ", ".join(available))
        else:
            lines.append("  （无）")

        lines.append("")
        lines.append("用法: /loadplugin <名>  /unloadplugin <名>")
        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    def _cmd_plugin_load(self, raw_name: str, channel: str, area: str):
        """动态加载插件。"""
        name = self._normalize_plugin_name(raw_name)
        if not name:
            self.sender.send_message("[x] 插件名不合法，仅支持字母/数字/下划线", channel=channel, area=area)
            return
        ok, msg = load_plugin(self._plugin_registry, name, "plugins", handler=self)
        prefix = "[ok]" if ok else "[x]"
        self.sender.send_message(f"{prefix} {msg}", channel=channel, area=area)

    def _cmd_plugin_unload(self, raw_name: str, channel: str, area: str):
        """动态卸载插件。"""
        name = self._normalize_plugin_name(raw_name)
        if not name:
            self.sender.send_message("[x] 插件名不合法，仅支持字母/数字/下划线", channel=channel, area=area)
            return
        ok, msg = unload_plugin(self._plugin_registry, name, handler=self)
        prefix = "[ok]" if ok else "[x]"
        self.sender.send_message(f"{prefix} {msg}", channel=channel, area=area)

    def _cmd_help(self, channel: str, area: str, user: str = ""):
        is_admin = self._is_admin(user)
        role_label = "管理员" if is_admin else "普通用户"
        plugin_caps = self._plugin_registry.list_command_caps(public_only=not is_admin)

        ai_chat_available = (
            self.chat.ai_enabled
            and bool(getattr(self.chat, "_ai_key", ""))
            and bool(getattr(self.chat, "_ai_base", ""))
            and bool(getattr(self.chat, "_ai_model", ""))
        )
        ai_image_available = (
            self.chat.img_enabled
            and bool(getattr(self.chat, "_img_key", ""))
            and bool(getattr(self.chat, "_img_base", ""))
            and bool(getattr(self.chat, "_img_model", ""))
        )

        lines = [
            "**Oopz Bot · 命令帮助** [" + role_label + "]",
            "",
            "**常用功能**",
            "@bot 每日一句  每日名言  |  /daily",
            "",
            "**个人信息**",
            "@bot 个人信息  个人基本信息  |  @bot 我的资料  自身详细资料",
            "/me  |  /myinfo",
        ]

        ai_cmds = []
        if ai_image_available:
            ai_cmds.append("@bot 画<描述>  AI 生成图片")
        if ai_chat_available:
            ai_cmds.append("@bot <任意内容>  AI 智能聊天")
        if ai_cmds:
            lines[2:2] = [
                "**AI 功能**",
                "  |  ".join(ai_cmds),
                "",
            ]

        if is_admin:
            lines += [
                "",
                "**音乐播放**",
                "@bot 播放<歌名>  搜索并播放  |  @bot 停止  停止播放  |  @bot 下一首  切换下一首",
                "@bot 队列  查看播放队列  |  @bot 随机  随机播放喜欢  |  @bot 喜欢列表  喜欢的音乐",
                "/bf <歌名>  /st  /next  /queue  |  /like  /like list  /like play",
                "",
                "**成员查询**",
                "@bot 成员  域成员在线  |  @bot 查看<用户>  他人详细资料  |  @bot 搜索<关键词>  搜索域成员",
                "/members  /whois  /search",
                "",
                "**语音频道**",
                "@bot 语音  语音在线成员  |  @bot 进入频道<ID>  进入指定频道",
                "/voice  /enter <频道ID>",
                "",
                "**角色管理**",
                "@bot 角色<用户>  域内角色  |  @bot 可分配角色<用户>  角色列表",
                "@bot 给身份组 <用户><身份组>  |  @bot 取消身份组 <用户><身份组>",
                "/role  /roles  /addrole  /removerole",
                "",
                "**管理操作**",
                "@bot 禁言<用户> [分钟]  禁言  |  @bot 解禁<用户>  解除  |  @bot 禁麦  @bot 解麦",
                "@bot 移出域<用户>  踢出域  |  @bot 解封<用户>  解除域内封禁  |  @bot 封禁列表  域封禁名单",
                "/禁言  /解禁  /禁麦  /解麦  |  /ban  /unblock  /blocklist",
                "@bot 撤回<消息ID>  撤回最后  撤回N条  |  /recall <ID|last|数量>",
                "@bot 自动撤回  查看/开 [秒]/关  |  /autorecall",
                "@bot 清理历史  清理历史日志  |  /clear history",
                "",
                "**插件扩展**",
                "@bot 插件列表  已加载/可加载  |  @bot 加载插件 <名>  @bot 卸载插件 <名>",
                "/plugins  |  /loadplugin <名>  /unloadplugin <名>",
            ]

        if plugin_caps:
            lines += [
                "",
                "**已加载扩展命令**",
            ]
            for item in plugin_caps:
                parts = []
                mentions = list(item.get("mention_prefixes", ()))
                slashes = list(item.get("slash_commands", ()))
                if mentions:
                    parts.append("@bot " + " / ".join(mentions[:5]))
                if slashes:
                    parts.append(" / ".join(slashes[:5]))
                summary = "  |  ".join(parts) if parts else "（无）"
                lines.append(f"{item['name']}: {summary}")

        lines += [
            "",
            "*发送脏话/违规内容将被自动禁言*",
        ]

        self.sender.send_message(
            "\n".join(lines),
            channel=channel,
            area=area,
            styleTags=["IMPORTANT"],
        )
