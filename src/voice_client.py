"""
Agora RTC 语音频道客户端（基于 Playwright + Agora Web SDK）

通过无头 Chromium 浏览器运行 Agora Web SDK，实现全平台兼容。
Bot 可以加入语音频道并推送音频。

依赖:
  - playwright (pip install playwright && playwright install chromium)
"""

import base64
import os
import queue
import random
import threading
import time
from typing import Optional, Tuple

import requests as http_requests

from logger_config import get_logger

logger = get_logger("Voice")

_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agora_player.html")


class VoiceClient:
    """
    Agora RTC 语音频道客户端。

    内部启动一个无头 Chromium（专用线程），加载 Agora Web SDK，
    所有浏览器操作均通过任务队列派发到 Playwright 线程执行。
    """

    def __init__(self, app_id: str, oopz_uid: str = "", init_timeout: float = 60):
        self._app_id = app_id
        self._oopz_uid = oopz_uid
        self._agora_uid = str(random.randint(100_000_000, 999_999_999))
        self._available = False
        self._playing = False
        self._play_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._identity_stop = threading.Event()
        self._identity_thread: Optional[threading.Thread] = None

        # Playwright 专用线程 + 任务队列
        self._task_queue: queue.Queue = queue.Queue()
        self._shutdown = threading.Event()
        self._init_done = threading.Event()
        self._init_error: Optional[str] = None

        pw_thread = threading.Thread(target=self._pw_thread_loop, daemon=True)
        pw_thread.start()

        if not self._init_done.wait(timeout=init_timeout):
            logger.error("Playwright 线程启动超时")
            return
        if self._init_error:
            logger.error(f"Agora 浏览器播放器初始化失败: {self._init_error}")
            return

        self._available = True
        logger.info(f"Agora 浏览器播放器已就绪 (uid={self._agora_uid})")

    # ------------------------------------------------------------------
    # Playwright 专用线程
    # ------------------------------------------------------------------

    def _pw_thread_loop(self):
        """专用线程：初始化 Playwright 并持续处理任务队列。"""
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-web-security",
                    "--allow-file-access-from-files",
                    "--autoplay-policy=no-user-gesture-required",
                    "--use-fake-device-for-media-stream",
                    "--use-fake-ui-for-media-stream",
                ],
            )
            self._page = self._browser.new_page()
            self._page.set_default_timeout(60000)
            self._page.goto(f"file:///{_HTML_PATH.replace(os.sep, '/')}")
            self._page.wait_for_function("window.agoraReady()", timeout=15000)
        except Exception as e:
            self._init_error = str(e)
            self._init_done.set()
            return

        self._init_done.set()

        # 事件循环：处理从其他线程派发过来的任务
        while not self._shutdown.is_set():
            try:
                task = self._task_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if task is None:
                break
            fn, result_holder, error_holder, done_event = task
            try:
                result_holder.append(fn(self._page))
            except Exception as e:
                error_holder.append(e)
            done_event.set()

        # 清理
        try:
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass

    def _run_on_pw(self, fn, timeout=60):
        """
        在 Playwright 线程上执行 fn(page)，阻塞等待结果。

        Args:
            fn: 接受 page 参数的 callable
            timeout: 最大等待秒数
        Returns:
            fn 的返回值
        Raises:
            fn 中抛出的异常
        """
        result_holder = []
        error_holder = []
        done = threading.Event()
        self._task_queue.put((fn, result_holder, error_holder, done))
        if not done.wait(timeout=timeout):
            raise TimeoutError("Playwright 操作超时")
        if error_holder:
            raise error_holder[0]
        return result_holder[0] if result_holder else None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._available

    @property
    def agora_uid(self) -> str:
        """Bot 的 Agora 数字 uid，用于请求 Token 和加入频道。"""
        return self._agora_uid

    @property
    def is_playing(self) -> bool:
        return self._playing

    def join(self, token: str, room_id: str, uid: Optional[int] = None) -> bool:
        """加入 Agora 语音房间。uid 默认使用 self._agora_uid。"""
        if not self._available:
            return False
        if uid is None:
            uid = int(self._agora_uid)
        try:
            logger.info(f"正在加入 Agora 房间: room={room_id}, uid={uid}")
            result = self._run_on_pw(
                lambda page: page.evaluate(
                    "([appId, token, roomId, uid]) => window.agoraJoin(appId, token, roomId, uid)",
                    [self._app_id, token, room_id, uid],
                )
            )
            if result and result.get("ok"):
                logger.info(f"已加入 Agora 房间: {room_id} (uid={result.get('uid')})")
                self._send_identity()
                self._start_identity_heartbeat()
                return True
            err = result.get("error", "未知") if result else "无响应"
            logger.warning(f"加入 Agora 房间失败: {err}")
            return False
        except Exception as e:
            logger.error(f"加入 Agora 房间异常: {e}")
            return False

    def play_audio(self, url: str):
        """下载音频并通过 Agora 推流到语音频道。"""
        if not self._available:
            return
        self.stop_audio()
        self._stop_event.clear()
        self._play_thread = threading.Thread(
            target=self._do_play, args=(url,), daemon=True
        )
        self._play_thread.start()

    def stop_audio(self):
        """停止当前音频推流。"""
        self._stop_event.set()
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=10)
        if self._available:
            try:
                self._run_on_pw(lambda page: page.evaluate("window.agoraStopAudio()"))
            except Exception:
                pass
        self._playing = False

    def pause_audio(self) -> bool:
        if not self._available:
            return False
        try:
            result = self._run_on_pw(lambda page: page.evaluate("window.agoraPause()"))
            return bool(result and result.get("ok"))
        except Exception as e:
            logger.warning(f"暂停失败: {e}")
            return False

    def resume_audio(self) -> bool:
        if not self._available:
            return False
        try:
            result = self._run_on_pw(lambda page: page.evaluate("window.agoraResume()"))
            return bool(result and result.get("ok"))
        except Exception as e:
            logger.warning(f"恢复播放失败: {e}")
            return False

    def seek_audio(self, time_sec: float) -> bool:
        if not self._available:
            return False
        try:
            result = self._run_on_pw(
                lambda page: page.evaluate(f"window.agoraSeek({time_sec})")
            )
            return bool(result and result.get("ok"))
        except Exception as e:
            logger.warning(f"跳转失败: {e}")
            return False

    def set_volume(self, vol: int) -> bool:
        if not self._available:
            return False
        try:
            result = self._run_on_pw(
                lambda page: page.evaluate(f"window.agoraSetVolume({vol})")
            )
            return bool(result and result.get("ok"))
        except Exception as e:
            logger.warning(f"设置音量失败: {e}")
            return False

    def leave(self):
        """离开当前 Agora 房间。"""
        self._stop_identity_heartbeat()
        self.stop_audio()
        if not self._available:
            return
        try:
            self._run_on_pw(lambda page: page.evaluate("window.agoraLeave()"))
            logger.info("已离开 Agora 房间")
        except Exception as e:
            logger.warning(f"离开 Agora 房间异常: {e}")

    def destroy(self):
        """释放浏览器资源（进程退出时调用）。"""
        self.leave()
        self._shutdown.set()
        self._task_queue.put(None)
        logger.info("Agora 浏览器播放器已释放")

    def get_state(self) -> str:
        """获取当前状态: idle / joined / playing / finished"""
        if not self._available:
            return "unavailable"
        try:
            return self._run_on_pw(lambda page: page.evaluate("window.agoraState()"))
        except Exception:
            return "error"

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _send_identity(self):
        """通过 Agora data stream 发送身份标识，让服务端关联 Oopz uid ↔ Agora uid。"""
        if not self._available or not self._oopz_uid:
            return
        try:
            agora_uid_int = int(self._agora_uid)
            result = self._run_on_pw(
                lambda page: page.evaluate(
                    "([oopzUid, agoraUid]) => window.agoraSendIdentity(oopzUid, agoraUid)",
                    [self._oopz_uid, agora_uid_int],
                )
            )
            if result and result.get("ok"):
                logger.debug("已发送 Agora 身份标识")
            else:
                err = result.get("error", "未知") if result else "无响应"
                logger.warning(f"发送 Agora 身份标识失败: {err}")
        except Exception as e:
            logger.warning(f"发送 Agora 身份标识异常: {e}")

    def _start_identity_heartbeat(self):
        """启动后台线程，定期重发身份标识。"""
        self._stop_identity_heartbeat()
        self._identity_stop.clear()

        def _loop():
            while not self._identity_stop.wait(timeout=10):
                self._send_identity()

        self._identity_thread = threading.Thread(target=_loop, daemon=True)
        self._identity_thread.start()

    def _stop_identity_heartbeat(self):
        """停止身份标识心跳。"""
        self._identity_stop.set()
        if self._identity_thread and self._identity_thread.is_alive():
            self._identity_thread.join(timeout=5)
        self._identity_thread = None

    def _do_play(self, url: str):
        """后台线程：流式下载音频（带超时与重试）→ 派发到 Playwright → Agora 推流"""
        self._playing = True
        try:
            audio_data, content_type = self._download_audio_with_retry(url)
            if audio_data is None or self._stop_event.is_set():
                return

            logger.info(f"音频下载完成: {len(audio_data)} bytes")
            b64 = base64.b64encode(audio_data).decode("ascii")
            if "octet-stream" in (content_type or ""):
                content_type = "audio/mpeg"

            result = self._run_on_pw(
                lambda page: page.evaluate(
                    "([b64, mime]) => window.agoraPlayLocal(b64, mime)",
                    [b64, content_type],
                )
            )

            if result and result.get("ok"):
                duration = result.get("duration", 0)
                logger.info(f"Agora 推流已开始 (时长: {duration:.1f}s)")

                while not self._stop_event.is_set():
                    state = self.get_state()
                    if state == "finished":
                        logger.info("Agora 推流播放完成")
                        break
                    time.sleep(2)
            else:
                err = result.get("error", "未知") if result else "无响应"
                logger.warning(f"Agora 推流启动失败: {err}")

        except http_requests.RequestException as e:
            logger.error(f"音频下载失败: {e}")
        except Exception as e:
            logger.error(f"Agora 推流异常: {e}")
        finally:
            self._playing = False

    def _download_audio_with_retry(self, url: str) -> Tuple[Optional[bytes], str]:
        """流式下载音频，弱网时使用更长超时与重试。返回 (音频数据, content_type)。"""
        try:
            from config import NETEASE_CLOUD
            connect_timeout = 15
            read_timeout = NETEASE_CLOUD.get("audio_download_timeout", 120)
            max_retries = NETEASE_CLOUD.get("audio_download_retries", 2)
        except Exception:
            connect_timeout, read_timeout, max_retries = 15, 120, 2

        last_error = None
        content_type = "audio/mpeg"
        for attempt in range(max_retries + 1):
            if self._stop_event.is_set():
                return None, content_type
            try:
                logger.info(f"正在下载音频 ({attempt + 1}/{max_retries + 1}): {url[:80]}...")
                resp = http_requests.get(
                    url,
                    timeout=(connect_timeout, read_timeout),
                    stream=True,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0.0.0 Safari/537.36", "Referer": "https://music.163.com/"},
                )
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type") or "audio/mpeg"

                chunks = []
                for chunk in resp.iter_content(chunk_size=65536):
                    if self._stop_event.is_set():
                        return None, content_type
                    if chunk:
                        chunks.append(chunk)
                data = b"".join(chunks)
                if data:
                    return data, content_type
            except http_requests.RequestException as e:
                last_error = e
                logger.warning(f"音频下载尝试 {attempt + 1} 失败: {e}")
                if attempt < max_retries:
                    backoff = 2 * (attempt + 1)
                    logger.info(f"{backoff}s 后重试...")
                    time.sleep(backoff)

        if last_error:
            raise last_error
        return None, content_type
