"""语音客户端构建。"""

from typing import Optional

from config import OOPZ_CONFIG
from logger_config import setup_logger
from voice_client import VoiceClient

logger = setup_logger("VoiceRuntime")


class VoiceRuntimeBuilder:
    """负责构建语音客户端。"""

    def build(self) -> Optional[VoiceClient]:
        agora_app_id = OOPZ_CONFIG.get("agora_app_id", "")
        if not agora_app_id:
            return None

        init_timeout = OOPZ_CONFIG.get("agora_init_timeout", 60)
        voice = VoiceClient(
            agora_app_id,
            oopz_uid=OOPZ_CONFIG.get("person_uid", ""),
            init_timeout=init_timeout,
        )
        if voice.available:
            logger.info("Agora 语音频道已启用。")
            return voice

        logger.warning("Agora 语音频道初始化失败。")
        return None
