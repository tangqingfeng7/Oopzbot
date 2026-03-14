"""
AudioService - Python 音频播放服务
使用 ffplay 播放音频，通过 Redis 同步播放状态
兼容 oopzBOTS 的 C# AudioService 接口
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional

import redis
import requests
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 确保 print 实时输出
sys.stdout.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AudioService] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("AudioService")

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

REDIS_CONFIG = {
    "host": "127.0.0.1",
    "port": 6379,
    "password": "",
    "db": 0,
    "decode_responses": True,
}

PORT = 5000

KEY_CURRENT = "music:current"
KEY_PLAYER_STATUS = "music:player_status"

# 查找 ffplay 可执行文件路径
FFPLAY_BIN = "ffplay"

def _find_ffplay() -> str:
    """在系统中查找 ffplay，包括 winget 安装路径"""
    import shutil
    path = shutil.which("ffplay")
    if path:
        return path
    # winget 安装的默认位置
    winget_link = os.path.expanduser(
        r"~\AppData\Local\Microsoft\WinGet\Links\ffplay.exe"
    )
    if os.path.isfile(winget_link):
        return winget_link
    # winget 包目录搜索
    winget_pkg = os.path.expanduser(
        r"~\AppData\Local\Microsoft\WinGet\Packages"
    )
    if os.path.isdir(winget_pkg):
        for root, dirs, files in os.walk(winget_pkg):
            if "ffplay.exe" in files:
                return os.path.join(root, "ffplay.exe")
    return "ffplay"

FFPLAY_BIN = _find_ffplay()

# ---------------------------------------------------------------------------
# Redis 连接
# ---------------------------------------------------------------------------

_redis: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis(**REDIS_CONFIG)
    return _redis


def _update_status(playing: bool, play_uuid: Optional[str] = None):
    """更新 Redis 中的播放器状态"""
    status = {"playing": playing, "playUuid": play_uuid}
    get_redis().set(KEY_PLAYER_STATUS, json.dumps(status, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 播放器核心
# ---------------------------------------------------------------------------


class AudioPlayer:
    """管理 ffplay 子进程的播放器"""

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._current_uuid: Optional[str] = None
        self._current_url: Optional[str] = None
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._temp_file: Optional[str] = None

        # 进度追踪
        self._play_start_time: float = 0       # ffplay 启动时间戳
        self._seek_offset: float = 0           # 跳转偏移量（秒）
        self._paused: bool = False             # 是否暂停
        self._pause_start: float = 0           # 暂停开始时间
        self._total_paused: float = 0          # 累计暂停时长
        self._duration: float = 0              # 歌曲总时长（秒）

        # 启动时设置初始状态
        _update_status(False, None)

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def _get_duration(self, file_path: str) -> float:
        """用 ffprobe 获取音频文件时长（秒）"""
        try:
            import re
            ffprobe_bin = re.sub(r"ffplay", "ffprobe", FFPLAY_BIN, flags=re.IGNORECASE)
            result = subprocess.run(
                [ffprobe_bin, "-v", "quiet", "-show_entries",
                 "format=duration", "-of", "csv=p=0", file_path],
                capture_output=True, text=True, timeout=10,
            )
            return float(result.stdout.strip())
        except Exception as e:
            log.warning(f"ffprobe 获取时长失败: {e}")
            return 0

    def _get_position(self) -> float:
        """获取当前播放位置（秒）"""
        with self._lock:
            if not self._play_start_time:
                return 0
            if self._paused:
                elapsed = self._pause_start - self._play_start_time - self._total_paused
            else:
                elapsed = time.time() - self._play_start_time - self._total_paused
            return self._seek_offset + max(0, elapsed)

    def play(self, url: str, model: Optional[str] = None, uuid: Optional[str] = None) -> dict:
        """开始播放音频"""
        self.stop(internal=True)

        with self._lock:
            self._current_uuid = uuid
            self._current_url = url

        _update_status(True, uuid)
        log.info(f"开始播放 (UUID: {uuid}): {url[:80]}...")

        # 在后台线程中下载并播放
        t = threading.Thread(target=self._download_and_play, args=(url, uuid), daemon=True)
        t.start()

        return {"status": True, "message": "播放已开始", "uuid": uuid}

    def _download_and_play(self, url: str, uuid: Optional[str]):
        """下载音频文件并用 ffplay 播放"""
        temp_path = None
        try:
            # 下载到临时文件（ffplay 对某些网易云 URL 的直接播放不稳定）
            resp = requests.get(url, timeout=30, stream=True, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36",
                "Referer": "https://music.163.com/",
            })
            resp.raise_for_status()

            suffix = ".mp3"
            content_type = resp.headers.get("Content-Type", "")
            if "mp4" in content_type or "m4a" in content_type:
                suffix = ".m4a"
            elif "flac" in content_type:
                suffix = ".flac"

            fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix="audio_")
            with os.fdopen(fd, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)

            with self._lock:
                self._temp_file = temp_path

            # 获取音频时长
            duration = self._get_duration(temp_path)
            log.info(f"下载完成 ({os.path.getsize(temp_path)} bytes, 时长: {duration:.1f}s), 开始播放")

            proc = subprocess.Popen(
                [FFPLAY_BIN, "-nodisp", "-autoexit", "-loglevel", "quiet", temp_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            with self._lock:
                self._process = proc
                self._play_start_time = time.time()
                self._seek_offset = 0
                self._paused = False
                self._pause_start = 0
                self._total_paused = 0
                self._duration = duration

            # 启动监控线程，等待播放结束
            self._monitor_thread = threading.Thread(
                target=self._wait_for_finish, args=(proc, uuid, temp_path), daemon=True
            )
            self._monitor_thread.start()

        except Exception as e:
            log.error(f"下载/播放失败: {e}")
            _update_status(False, None)
            self._cleanup_current(uuid)
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _wait_for_finish(self, proc: subprocess.Popen, uuid: Optional[str], temp_path: Optional[str]):
        """等待 ffplay 进程结束，然后清理状态"""
        proc.wait()

        with self._lock:
            is_current = self._process is proc

        if not is_current:
            # 进程已被 seek/stop 替换，不做清理（新进程仍在使用临时文件）
            return

        log.info(f"播放完成 (UUID: {uuid})")

        _update_status(False, None)
        self._cleanup_current(uuid)

        with self._lock:
            self._process = None
            self._current_uuid = None
            self._current_url = None
            self._temp_file = None
            self._play_start_time = 0
            self._seek_offset = 0
            self._paused = False
            self._pause_start = 0
            self._total_paused = 0
            self._duration = 0

        # 清理临时文件（只有在进程自然结束时才删除）
        if temp_path and os.path.exists(temp_path):
            try:
                time.sleep(0.5)
                os.remove(temp_path)
            except OSError:
                pass

    def _cleanup_current(self, uuid: Optional[str]):
        """播放完成后清理 Redis 中的 music:current"""
        try:
            r = get_redis()
            current_data = r.get(KEY_CURRENT)
            if current_data:
                current = json.loads(current_data)
                # 只清理属于当前 UUID 的记录（避免误清新歌曲）
                if uuid and current.get("play_uuid") == uuid:
                    r.delete(KEY_CURRENT)
                    log.info(f"已清空 music:current (UUID: {uuid})")
                elif not uuid:
                    r.delete(KEY_CURRENT)
                    log.info("已清空 music:current")
        except Exception as e:
            log.error(f"清理 music:current 失败: {e}")

    def stop(self, internal: bool = False) -> dict:
        """停止播放"""
        with self._lock:
            proc = self._process
            temp_file = self._temp_file

        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception:
                pass

            log.info("已停止播放")

        with self._lock:
            self._process = None
            uuid = self._current_uuid
            self._current_uuid = None
            self._current_url = None
            self._temp_file = None

        _update_status(False, None)

        if not internal:
            self._cleanup_current(uuid)

        # 清理临时文件
        if temp_file and os.path.exists(temp_file):
            try:
                time.sleep(0.5)
                os.remove(temp_file)
            except OSError:
                pass

        # 重置进度状态
        with self._lock:
            self._play_start_time = 0
            self._seek_offset = 0
            self._paused = False
            self._pause_start = 0
            self._total_paused = 0
            self._duration = 0

        return {"status": True, "message": "已停止", "playing": False}

    def pause(self) -> dict:
        """暂停播放"""
        import psutil
        with self._lock:
            proc = self._process
            if not proc or proc.poll() is not None:
                return {"status": False, "message": "没有正在播放的内容"}
            if self._paused:
                return {"status": True, "message": "已经是暂停状态"}
            try:
                p = psutil.Process(proc.pid)
                p.suspend()
                self._paused = True
                self._pause_start = time.time()
                log.info("已暂停播放")
                return {"status": True, "message": "已暂停", "paused": True}
            except Exception as e:
                log.error(f"暂停失败: {e}")
                return {"status": False, "message": f"暂停失败: {e}"}

    def resume(self) -> dict:
        """恢复播放"""
        import psutil
        with self._lock:
            proc = self._process
            if not proc or proc.poll() is not None:
                return {"status": False, "message": "没有正在播放的内容"}
            if not self._paused:
                return {"status": True, "message": "已经在播放中"}
            try:
                p = psutil.Process(proc.pid)
                p.resume()
                self._total_paused += time.time() - self._pause_start
                self._paused = False
                self._pause_start = 0
                log.info("已恢复播放")
                return {"status": True, "message": "已恢复", "paused": False}
            except Exception as e:
                log.error(f"恢复失败: {e}")
                return {"status": False, "message": f"恢复失败: {e}"}

    def seek(self, position: float) -> dict:
        """跳转到指定位置（秒）"""
        with self._lock:
            proc = self._process
            temp_file = self._temp_file
            uuid = self._current_uuid
            duration = self._duration
            was_paused = self._paused

        if not proc or not temp_file:
            return {"status": False, "message": "没有正在播放的内容"}

        if not os.path.exists(temp_file):
            return {"status": False, "message": "音频文件不存在"}

        position = max(0, min(position, duration)) if duration > 0 else max(0, position)

        # 如果暂停了，先恢复（避免 kill 挂起的进程出问题）
        if was_paused:
            try:
                import psutil
                p = psutil.Process(proc.pid)
                p.resume()
            except Exception:
                pass

        # 停止当前 ffplay
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        # 用 -ss 重新启动 ffplay
        new_proc = subprocess.Popen(
            [FFPLAY_BIN, "-nodisp", "-autoexit", "-loglevel", "quiet",
             "-ss", str(position), temp_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        with self._lock:
            self._process = new_proc
            self._play_start_time = time.time()
            self._seek_offset = position
            self._paused = False
            self._pause_start = 0
            self._total_paused = 0

        # 新的监控线程
        self._monitor_thread = threading.Thread(
            target=self._wait_for_finish, args=(new_proc, uuid, temp_file), daemon=True
        )
        self._monitor_thread.start()

        log.info(f"跳转到 {position:.1f}s")
        return {"status": True, "message": f"已跳转到 {position:.1f}s", "position": position}

    def get_status(self) -> dict:
        """获取当前播放状态（含进度信息）"""
        with self._lock:
            playing = self._process is not None and self._process.poll() is None
            uuid = self._current_uuid
            url = self._current_url
            paused = self._paused
            duration = self._duration

        position = self._get_position() if playing or paused else 0
        # 不要超过总时长
        if duration > 0:
            position = min(position, duration)

        # 从 Redis 获取当前歌曲信息
        song_info = None
        try:
            r = get_redis()
            current_data = r.get(KEY_CURRENT)
            if current_data:
                song_info = json.loads(current_data)
        except Exception:
            pass

        return {
            "playing": playing and not paused,
            "paused": paused,
            "playUuid": uuid,
            "url": url,
            "position": round(position, 1),
            "duration": round(duration, 1),
            "song": {
                "name": song_info.get("name", "") if song_info else "",
                "artists": song_info.get("artists", "") if song_info else "",
                "album": song_info.get("album", "") if song_info else "",
                "cover": song_info.get("cover", "") if song_info else "",
            } if song_info else None,
        }


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------

player = AudioPlayer()

app = FastAPI(title="AudioService", description="Python 音频播放服务")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/play")
def api_play(url: str, model: str = None, uuid: str = None):
    """播放音频
    - url: 音频 URL
    - model: 播放模式（如 'qq'）
    - uuid: 播放追踪 UUID
    """
    return player.play(url, model=model, uuid=uuid)


@app.get("/stop")
def api_stop():
    """停止播放"""
    return player.stop()


@app.get("/pause")
def api_pause():
    """暂停播放"""
    return player.pause()


@app.get("/resume")
def api_resume():
    """恢复播放"""
    return player.resume()


@app.get("/seek")
def api_seek(position: float):
    """跳转到指定位置（秒）"""
    return player.seek(position)


@app.get("/status")
def api_status():
    """获取播放器状态（含进度）"""
    return player.get_status()


@app.get("/health")
def api_health():
    """健康检查"""
    return {"status": "ok", "service": "AudioService"}


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info(f"启动中... 端口: {PORT}")
    log.info(f"ffplay 路径: {FFPLAY_BIN}")
    try:
        r = get_redis()
        r.ping()
        log.info("Redis 连接成功")
        # 启动时清理残留状态，防止旧数据导致 Bot 判断异常
        r.delete(KEY_PLAYER_STATUS)
        r.delete(KEY_CURRENT)
        log.info("已清理 Redis 残留播放状态")
    except Exception as e:
        log.error(f"Redis 连接失败: {e}")

    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
