import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oopz_sdk import OopzBot  # noqa: E402
from oopz_sdk.models import Attachment, ImageAttachment, UploadedFileResult  # noqa: E402
from oopz_sdk.models.segment import Image as ImageSegment  # noqa: E402
from oopz_sdk.models.segment import parse_message_segments  # noqa: E402
from oopz_sdk.testing.factories import make_config  # noqa: E402
from PIL import Image  # noqa: E402

from app.infrastructure.gateways.sender_gateway import SenderGateway  # noqa: E402


class ImageMessageTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "card.png"
        Image.new("RGB", (64, 96), "black").save(self.path)
        self.bot = OopzBot(make_config())
        self.gateway = SenderGateway(self.bot)
        self.upload = AsyncMock(return_value=UploadedFileResult.from_manually(
            "/im/card.png", "https://example.com/card.png", "IMAGE", "card.png",
        ))
        self.bot.media.upload_bytes = self.upload
        self.request = AsyncMock(return_value={"messageId": "sent-image", "timestamp": "123"})
        self.bot.rest.transport.request_data = self.request
        self.open_private_session = AsyncMock(return_value=SimpleNamespace(session_id="private-channel"))
        self.bot.messages.open_private_session = self.open_private_session

    async def asyncTearDown(self):
        await self.bot.stop()

    def assert_image_can_be_parsed(self, caption):
        self.upload.assert_awaited_once()
        call = self.request.await_args
        assert call is not None
        body = call.kwargs["body"]
        message = body.get("message", body)
        attachments: list[Attachment] = [ImageAttachment.model_validate(item) for item in message["attachments"]]
        segments = parse_message_segments(message["content"], attachments=attachments)
        images = [segment for segment in segments if isinstance(segment, ImageSegment)]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].file_key, "/im/card.png")
        self.assertEqual((images[0].width, images[0].height), (64, 96))
        self.assertEqual(images[0].file_size, self.path.stat().st_size)
        self.assertEqual(message["text"], message["content"])
        self.assertTrue(message["content"].endswith(caption))
        self.assertEqual(message["content"].count("![IMAGEw"), 1)

    def assert_native_image(self, endpoint):
        self.upload.assert_awaited_once()
        call = self.request.await_args
        assert call is not None
        self.assertEqual(call.args, ("POST", endpoint))
        body = call.kwargs["body"]
        image = ImageAttachment.model_validate(body["rawImage"])
        self.assertEqual(image.file_key, "/im/card.png")
        self.assertEqual((image.width, image.height), (64, 96))
        self.assertEqual(image.file_size, self.path.stat().st_size)
        upload_call = self.upload.await_args
        assert upload_call is not None
        uploaded_bytes = upload_call.args[0]
        self.assertEqual(uploaded_bytes, self.path.read_bytes())
        self.assertEqual(body["rawImage"]["hash"], hashlib.md5(uploaded_bytes).hexdigest())
        self.assertNotIn("content", body)
        self.assertNotIn("attachments", body)

    async def test_channel_image_uses_the_native_image_endpoint(self):
        await self.gateway.upload_and_send_image(
            str(self.path), channel="channel", area="area", auto_recall=False,
        )
        self.assert_native_image("/rtc/v1/gim/v1/sendImage")

    async def test_private_image_uses_the_native_image_endpoint(self):
        result = await self.gateway.upload_and_send_private_image("person", str(self.path))
        self.assertEqual(result.message_id, "sent-image")
        self.assert_native_image("/rtc/v1/im/v1/sendImage")
        self.open_private_session.assert_awaited_once_with("person")

    async def test_channel_image_with_caption_contains_an_inline_image_reference(self):
        await self.gateway.upload_and_send_image(
            str(self.path), text="召唤师战绩", channel="channel", area="area", auto_recall=False,
        )
        self.assert_image_can_be_parsed("召唤师战绩")

    async def test_private_image_with_caption_contains_an_inline_image_reference(self):
        result = await self.gateway.upload_and_send_private_image("person", str(self.path), text="召唤师战绩")
        self.assertEqual(result.message_id, "sent-image")
        self.assert_image_can_be_parsed("召唤师战绩")

    async def test_url_upload_returns_image_model_with_dimensions_and_hash(self):
        raw = self.path.read_bytes()
        with patch("app.infrastructure.gateways.sender_gateway.SafeRemoteFetcher") as fetcher:
            fetcher.return_value.fetch.return_value = (raw, "image/png")
            result = await self.gateway.upload_image_from_url("https://example.com/cover")
        self.assertIsInstance(result, ImageAttachment)
        self.assertEqual((result.width, result.height, result.file_size), (64, 96, len(raw)))
        self.assertEqual(result.hash, hashlib.md5(raw).hexdigest())
        self.upload.assert_awaited_once_with(raw, file_type="IMAGE", ext=".png", display_name="")
        fetcher.return_value.fetch.assert_called_once_with(
            "https://example.com/cover", max_bytes=20 * 1024 * 1024, timeout=(10, 60),
        )

    async def test_upload_failure_propagates_without_sending(self):
        error = RuntimeError("上传失败")
        self.upload.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            await self.gateway.upload_and_send_image(str(self.path), channel="channel", area="area")
        self.assertIs(caught.exception, error)
        self.request.assert_not_awaited()

    async def test_native_image_preserves_announcement_style_and_auto_recall(self):
        recall = AsyncMock()
        self.gateway._schedule_auto_recall = recall
        await self.gateway.upload_and_send_image(
            str(self.path), channel="channel", area="area", styleTags=["IMPORTANT"],
        )
        self.assert_native_image("/rtc/v1/gim/v1/sendImage")
        assert self.request.await_args is not None
        self.assertEqual(self.request.await_args.kwargs["body"]["styleTags"], ["IMPORTANT"])
        recall.assert_awaited_once_with("sent-image", "area", "channel", "123")
