"""
聊天模块
支持关键词匹配 + 豆包 AI 大模型回复 + AI 图片生成
"""

import requests
from typing import Optional

from config import CHAT_CONFIG, DOUBAO_CONFIG, DOUBAO_IMAGE_CONFIG
from logger_config import get_logger

logger = get_logger("Chat")


class ChatHandler:
    """关键词匹配 + AI 聊天回复"""

    def __init__(self):
        self.enabled = CHAT_CONFIG.get("enabled", True)
        self.keyword_replies: dict = CHAT_CONFIG.get("keyword_replies", {})

        # 豆包 AI
        self.ai_enabled = DOUBAO_CONFIG.get("enabled", False)
        self._ai_base = DOUBAO_CONFIG.get("base_url", "").rstrip("/")
        self._ai_key = DOUBAO_CONFIG.get("api_key", "")
        self._ai_model = DOUBAO_CONFIG.get("model", "")
        self._system_prompt = DOUBAO_CONFIG.get("system_prompt", "你是一个友好的聊天机器人。")
        self._max_tokens = DOUBAO_CONFIG.get("max_tokens", 256)
        self._temperature = DOUBAO_CONFIG.get("temperature", 0.7)

        # 图片生成
        self.img_enabled = DOUBAO_IMAGE_CONFIG.get("enabled", False)
        self._img_base = DOUBAO_IMAGE_CONFIG.get("base_url", "").rstrip("/")
        self._img_key = DOUBAO_IMAGE_CONFIG.get("api_key", "")
        self._img_model = DOUBAO_IMAGE_CONFIG.get("model", "")
        self._img_size = DOUBAO_IMAGE_CONFIG.get("size", "1920x1920")
        self._img_watermark = DOUBAO_IMAGE_CONFIG.get("watermark", False)

        ai_status = "已启用" if (self.ai_enabled and self._ai_key) else "未启用"
        img_status = "已启用" if (self.img_enabled and self._img_key) else "未启用"
        logger.info(f"聊天模块已初始化，关键词: {len(self.keyword_replies)} 个，AI: {ai_status}，图片生成: {img_status}")

    def try_reply(self, content: str) -> Optional[str]:
        """
        尝试根据消息内容生成自动回复。
        优先关键词匹配，无匹配则不回复（普通消息不触发 AI）。
        """
        if not self.enabled or not content:
            return None

        content_lower = content.strip().lower()

        for keyword, reply in self.keyword_replies.items():
            if keyword.lower() == content_lower:
                return reply

        for keyword, reply in self.keyword_replies.items():
            if keyword.lower() in content_lower:
                return reply

        return None

    def ai_reply(self, content: str) -> Optional[str]:
        """
        调用豆包 AI 生成回复。
        用于 @bot 触发的非指令消息。
        """
        if not self.ai_enabled or not self._ai_key or not self._ai_base:
            return None

        try:
            resp = requests.post(
                f"{self._ai_base}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._ai_key}",
                },
                json={
                    "model": self._ai_model,
                    "messages": [
                        {"role": "system", "content": self._system_prompt},
                        {"role": "user", "content": content},
                    ],
                    "max_tokens": self._max_tokens,
                    "temperature": self._temperature,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            reply = data["choices"][0]["message"]["content"].strip()
            logger.info(f"AI 回复: {content[:30]}... -> {reply[:50]}...")
            return reply

        except Exception as e:
            logger.error(f"豆包 AI 请求失败: {e}")
            return None

    def generate_image(self, prompt: str) -> Optional[str]:
        """
        调用豆包 Seedream 生成图片。
        返回图片 URL，失败返回 None。
        """
        if not self.img_enabled or not self._img_key or not self._img_base:
            return None

        try:
            logger.info(f"图片生成请求: {prompt[:50]}...")
            resp = requests.post(
                f"{self._img_base}/images/generations",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._img_key}",
                },
                json={
                    "model": self._img_model,
                    "prompt": prompt,
                    "n": 1,
                    "size": self._img_size,
                    "watermark": self._img_watermark,
                    "response_format": "url",
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

            url = data["data"][0]["url"]
            logger.info(f"图片生成成功: {prompt[:30]}...")
            return url

        except Exception as e:
            logger.error(f"图片生成失败: {e}")
            return None

    def check_profanity(self, content: str) -> Optional[str]:
        """
        调用豆包 AI 判断消息是否含有辱骂/攻击性内容。
        返回违规原因字符串，未违规返回 None。
        """
        if not self.ai_enabled or not self._ai_key or not self._ai_base:
            return None

        prompt = (
            f"消息: \"{content}\"\n\n"
            "判断这条消息是否违规。违规包括:\n"
            "1. 骂人、辱骂、人身攻击（如: 傻逼、你妈死了、滚、废物）\n"
            "2. 诅咒（如: 去死、死全家、你骂死了、不得好死）\n"
            "3. 威胁、恐吓\n"
            "4. 侮辱性称呼（如: 狗、猪、垃圾）\n"
            "5. 谐音骂人、拆字骂人、暗示性辱骂\n"
            "6. 任何带有攻击意图的内容\n\n"
            "注意: 这是游戏社区聊天，请从严判定，宁可误判也不要漏判。\n"
            "只回复\"正常\"或\"违规:原因\"（原因不超过10字），不要解释。"
        )
        try:
            resp = requests.post(
                f"{self._ai_base}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._ai_key}",
                },
                json={
                    "model": self._ai_model,
                    "messages": [
                        {"role": "system", "content": "你是游戏社区内容审核AI，职责是严格识别一切辱骂、攻击、诅咒内容。从严判定，宁可误判也不能漏判。只输出判定结果。"},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 32,
                    "temperature": 0.0,
                },
                timeout=5,
            )
            resp.raise_for_status()
            result = resp.json()["choices"][0]["message"]["content"].strip()
            logger.info(f"AI 审核: \"{content[:30]}\" -> {result}")

            if result.startswith("违规"):
                reason = result.split(":", 1)[-1].split("：", 1)[-1].strip() or "辱骂内容"
                return reason
            return None

        except Exception as e:
            logger.error(f"AI 审核请求失败: {e}")
            return None

    def add_keyword(self, keyword: str, reply: str):
        self.keyword_replies[keyword] = reply
        logger.info(f"添加关键词: '{keyword}' -> '{reply}'")

    def remove_keyword(self, keyword: str) -> bool:
        if keyword in self.keyword_replies:
            del self.keyword_replies[keyword]
            return True
        return False

    def list_keywords(self) -> dict:
        return dict(self.keyword_replies)
