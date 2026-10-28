import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


class DeadCodeCleanupContractsTest(unittest.TestCase):
    def test_removed_legacy_files_and_dependency_stay_removed(self) -> None:
        removed_paths = (
            "src/web/assets/admin/webintosh-admin.css",
            "plugins/_shared/lol_common.py",
            "tools/audio_service.py",
        )
        for relative_path in removed_paths:
            with self.subTest(path=relative_path):
                self.assertFalse((REPO_ROOT / relative_path).exists())

        self.assertNotIn("psutil", _read("requirements.txt"))
        self.assertNotIn("audio_service.py", _read("docs/architecture.md"))

    def test_web_player_only_mounts_the_current_static_assets(self) -> None:
        source = _read("src/web/web_player.py")

        self.assertIn('"/admin-assets"', source)
        self.assertNotIn("webintosh-assets", source)
        self.assertNotIn("Webintosh", source)

    def test_agora_page_exports_every_method_python_calls(self) -> None:
        """语音页已随 SDK 内置，浏览器桥两侧必须对齐。

        原来的清单是「这些已删方法不要回来」，页面搬进 SDK 后这个方向不再由本仓库
        决定；真正会在运行时炸的是反向缺口——Python 调了页面没导出的方法。
        """
        import re

        page = _read("src/oopz_sdk/assets/voice/agora_player.html")
        bridge = _read("src/oopz_sdk/transport/voice_browser.py")

        exported = set(re.findall(r"window\.(agora[A-Za-z]+)\s*=", page))
        # 只取被当作函数调用的名字，属性访问（如 agoraUid）不在导出契约内
        called = set(re.findall(r"(agora[A-Za-z]+)\s*\(", bridge))

        self.assertEqual(
            called - exported,
            set(),
            "Python 调用了语音页未导出的方法",
        )

    def test_agora_page_reapplies_saved_volume_to_every_new_track(self) -> None:
        """音量恢复发生在首条音轨创建前，且每首歌都会新建音轨。

        页面必须在无 track 时也记住音量，并在新 track 开始前应用，
        否则实际音量会一直是 Agora 默认值，直到用户再拖一次滑块。
        """
        page = _read("src/oopz_sdk/assets/voice/agora_player.html")
        publish_start = page.index("async function publishTrackAsPlayback")
        publish_end = page.index("window.agoraPlayAudio", publish_start)
        publish_body = page[publish_start:publish_end]
        set_volume_start = page.index("window.agoraSetVolume")
        set_volume_end = page.index("window.agoraGetCurrentTime", set_volume_start)
        set_volume_body = page[set_volume_start:set_volume_end]

        self.assertIn("let _currentVolume = 100;", page)
        self.assertIn("localTrack.setVolume(_currentVolume);", publish_body)
        self.assertLess(
            publish_body.index("localTrack.setVolume(_currentVolume);"),
            publish_body.index("localTrack.startProcessAudioBuffer"),
        )
        self.assertIn("_currentVolume = Math.max(0, Math.min(100, parsed));", set_volume_body)
        self.assertIn("return { ok: true, pending: true, volume: _currentVolume };", set_volume_body)

    def test_agora_remote_audio_streams_before_the_full_file_is_downloaded(self) -> None:
        """远程无损音频应使用媒体流音轨，不能退回整首下载解码后才发布。"""
        page = _read("src/oopz_sdk/assets/voice/agora_player.html")
        stream_start = page.index("async function publishStreamingUrlAsPlayback")
        stream_end = page.index("window.agoraPlayAudio", stream_start)
        stream_body = page[stream_start:stream_end]
        remote_start = page.index("window.agoraPlayAudio")
        remote_end = page.index("window.agoraPlayLocal", remote_start)
        remote_body = page[remote_start:remote_end]

        self.assertIn('document.createElement("audio")', stream_body)
        self.assertIn("createMediaElementSource(media)", stream_body)
        self.assertIn("createMediaStreamDestination()", stream_body)
        self.assertIn("AgoraRTC.createCustomAudioTrack({ mediaStreamTrack })", stream_body)
        self.assertIn("await waitForMediaCanPlay(media, gen)", stream_body)
        self.assertIn("await media.play()", stream_body)
        self.assertIn("publishStreamingUrlAsPlayback(url, gen)", remote_body)
        self.assertNotIn("createBufferSourceAudioTrack", remote_body)

    def test_agora_streaming_media_keeps_controls_and_cleanup(self) -> None:
        page = _read("src/oopz_sdk/assets/voice/agora_player.html")

        self.assertIn("disposeStreamingMedia(playback);", page)
        self.assertIn("activePlayback.media.pause();", page)
        self.assertIn("await activePlayback.media.play();", page)
        self.assertIn("activePlayback.media.currentTime =", page)
        self.assertIn('media.addEventListener("ended"', page)
        self.assertIn('media.addEventListener("error"', page)

    def test_voice_browser_warmup_loads_agora_sdk_before_first_join(self) -> None:
        page = _read("src/oopz_sdk/assets/voice/agora_player.html")
        project_transport = _read("src/oopz/sdk_transport.py")
        sdk_transport = _read("src/oopz_sdk/transport/voice_browser.py")

        self.assertIn("window.agoraWarmup = async () =>", page)
        self.assertIn("await loadAgoraSdk();", page)
        for source in (project_transport, sdk_transport):
            goto = source.index("await page.goto(html_path.as_uri())")
            warmup = source.index('await page.evaluate("() => window.agoraWarmup()")', goto)
            ready = source.index("self._page = page", warmup)
            self.assertLess(goto, warmup)
            self.assertLess(warmup, ready)

        self.assertIn("Promise.resolve(window.agoraWarmup())", project_transport)

    def test_agora_identity_uses_sdk_data_stream_before_raw_websocket(self) -> None:
        """身份心跳必须走 Agora SDK 的 data stream 请求。

        直接 ``ws.send`` 只说明浏览器把字节写进了 socket，不能证明 Agora
        网关接受了身份包。服务端随后会把 bot 从语音成员列表移除，表现为仍能
        听到音乐但频道里看不到 bot。旧 SDK 的裸 WebSocket 仅保留为兼容回退。
        """
        page = _read("src/oopz_sdk/assets/voice/agora_player.html")
        send_start = page.index("async function sendVoiceStateRaw")
        send_end = page.index("async function sendCurrentVoiceState", send_start)
        send_body = page[send_start:send_end]

        native_send = send_body.index("client.sendStreamMessage")
        raw_fallback = send_body.index("ws.send")
        self.assertLess(native_send, raw_fallback)
        self.assertIn('transport: "agora-client"', send_body)
        self.assertIn('transport: "raw-websocket-fallback"', send_body)

    def test_plugin_runtime_accessor_comes_from_shared_runtime_module(self) -> None:
        source = _read("src/web/admin/plugins.py")

        self.assertIn("from web.admin.shared import _get_plugin_runtime, cfg", source)
        self.assertNotIn("def _get_plugin_runtime", source)
        self.assertIn("def _get_plugin_host", source)

    def test_music_keeps_bypass_construction_guards(self) -> None:
        """封面预取要容忍绕过 __init__ 构造的实例。

        改成 asyncio 之后不再需要锁，状态收敛到 `_cover_prefetch` 一个字典，
        守卫也随之只剩这一处；但守卫本身不能丢——测试与部分运行路径会用
        `__new__` 造实例，缺属性时必须安静跳过而不是抛 AttributeError。
        """
        source = _read("src/music/music.py")

        self.assertIn('hasattr(self, "_cover_prefetch")', source)
        self.assertNotIn(
            "_cover_prefetch_lock",
            source,
            "asyncio 下不应再出现线程锁残留",
        )


if __name__ == "__main__":
    unittest.main()
