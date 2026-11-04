"""项目使用的域邀请查询与退域接口。"""

from oopz_sdk.models.base import BaseModel, OperationResult
from oopz_sdk.services.area import AreaService
from pydantic import Field


class AreaInviteDetail(BaseModel):
    invite_status: str = Field(default="", alias="status")
    invite_uid: str = Field(default="", alias="inviteUid")
    area_id: str = Field(default="", alias="area")
    area_name: str = Field(default="", alias="areaName")
    area_avatar: str = Field(default="", alias="areaAvatar")
    channel_id: str = Field(default="", alias="channel")
    channel_type: str = Field(default="", alias="channelType")
    channel_name: str = Field(default="", alias="channelName")
    banner: str = ""
    is_area_invite: bool = Field(default=False, alias="isAreaInvite")


class ProjectAreaService(AreaService):
    async def get_invite_detail(self, code: str) -> AreaInviteDetail:
        code = str(code or "").strip()
        if not code:
            raise ValueError("code is required for get_invite_detail")
        data = await self._request_data(
            "GET", "/invite/v1/codeDetail", params={"code": code}
        )
        return AreaInviteDetail.model_validate(data)

    async def leave_area(self, area: str) -> OperationResult:
        if not area.strip():
            raise ValueError("area is required for leave_area")
        data = await self._request_data(
            "DELETE", "/client/v1/area/v1/quit", params={"area": area}
        )
        return OperationResult.from_api(data)


def install_project_services(bot) -> None:
    bot.areas = bot.rest.areas = ProjectAreaService(
        bot, bot.config, bot.rest.transport, bot.rest.signer, bot.cache
    )
