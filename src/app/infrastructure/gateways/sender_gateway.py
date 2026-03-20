from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from oopz_sender import OopzSender


class SenderGateway:
    """隔离应用层对 OopzSender 具体实现的直接依赖。

    显式暴露高频业务方法以保留类型信息，低频方法仍通过 __getattr__ 透传。
    """

    def __init__(self, sender: OopzSender):
        self._sender = sender

    @property
    def raw(self) -> OopzSender:
        return self._sender

    # -- 消息发送 --

    def send_message(self, text: str, area: Optional[str] = None,
                     channel: Optional[str] = None, **kwargs):
        return self._sender.send_message(text, area=area, channel=channel, **kwargs)

    def send_private_message(self, target: str, text: str, **kwargs):
        return self._sender.send_private_message(target, text, **kwargs)

    def recall_message(self, message_id: str, **kwargs) -> dict:
        return self._sender.recall_message(message_id, **kwargs)

    # -- 成员/域查询 --

    def get_area_members(self, **kwargs) -> dict:
        return self._sender.get_area_members(**kwargs)

    def get_person_detail(self, **kwargs) -> dict:
        return self._sender.get_person_detail(**kwargs)

    def get_person_detail_full(self, uid: str, **kwargs) -> dict:
        return self._sender.get_person_detail_full(uid, **kwargs)

    def get_person_infos_batch(self, uids: list, **kwargs) -> dict:
        return self._sender.get_person_infos_batch(uids, **kwargs)

    def get_user_area_detail(self, uid: str, **kwargs) -> dict:
        return self._sender.get_user_area_detail(uid, **kwargs)

    def search_area_members(self, **kwargs):
        return self._sender.search_area_members(**kwargs)

    # -- 角色管理 --

    def get_assignable_roles(self, uid: str, **kwargs):
        return self._sender.get_assignable_roles(uid, **kwargs)

    def edit_user_role(self, uid: str, role_id, **kwargs) -> dict:
        return self._sender.edit_user_role(uid, role_id, **kwargs)

    # -- 审核管理 --

    def mute_user(self, uid: str, **kwargs) -> dict:
        return self._sender.mute_user(uid, **kwargs)

    def unmute_user(self, uid: str, **kwargs) -> dict:
        return self._sender.unmute_user(uid, **kwargs)

    def mute_mic(self, uid: str, **kwargs) -> dict:
        return self._sender.mute_mic(uid, **kwargs)

    def unmute_mic(self, uid: str, **kwargs) -> dict:
        return self._sender.unmute_mic(uid, **kwargs)

    def remove_from_area(self, uid: str, **kwargs) -> dict:
        return self._sender.remove_from_area(uid, **kwargs)

    def unblock_user_in_area(self, uid: str, **kwargs) -> dict:
        return self._sender.unblock_user_in_area(uid, **kwargs)

    def get_area_blocks(self, **kwargs) -> dict:
        return self._sender.get_area_blocks(**kwargs)

    # -- 语音频道 --

    def get_voice_channel_members(self, **kwargs):
        return self._sender.get_voice_channel_members(**kwargs)

    # -- 频道消息 --

    def get_channel_messages(self, **kwargs):
        return self._sender.get_channel_messages(**kwargs)

    def find_message_timestamp(self, message_id: str, **kwargs):
        return self._sender.find_message_timestamp(message_id, **kwargs)

    # -- 文件上传 --

    def upload_file_from_url(self, url: str, **kwargs):
        return self._sender.upload_file_from_url(url, **kwargs)

    # -- 其他 --

    def get_daily_speech(self, **kwargs) -> dict:
        return self._sender.get_daily_speech(**kwargs)

    def get_joined_areas(self, **kwargs):
        return self._sender.get_joined_areas(**kwargs)

    def __getattr__(self, name: str):
        return getattr(self._sender, name)
