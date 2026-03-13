"""命令处理相关服务注册表。"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.community.member_service import MemberService
from app.services.community.role_service import RoleService
from app.services.community.target_resolution_service import TargetResolutionService
from app.services.interaction.chat_interaction_service import ChatInteractionService
from app.services.interaction.common_command_service import CommonCommandService
from app.services.interaction.help_service import HelpService
from app.services.interaction.music_command_service import MusicCommandService
from app.services.plugins.plugin_management_service import PluginManagementService
from app.services.routing.command_access_service import CommandAccessService
from app.services.routing.command_message_service import CommandMessageService
from app.services.routing.command_router import CommandRouter
from app.services.routing.mention_command_router import MentionCommandRouter
from app.services.routing.slash_command_router import SlashCommandRouter
from app.services.safety.message_lookup_service import MessageLookupService
from app.services.safety.message_recall_scheduler import MessageRecallScheduler
from app.services.safety.moderation_service import ModerationService
from app.services.safety.profanity_guard_service import ProfanityGuardService
from app.services.safety.recall_service import RecallService


if TYPE_CHECKING:
    from command_handler import CommandHandler


@dataclass(frozen=True)
class RoutingServices:
    """命令和消息路由相关服务。"""

    access: CommandAccessService
    message: CommandMessageService
    command: CommandRouter
    mention: MentionCommandRouter
    slash: SlashCommandRouter


@dataclass(frozen=True)
class InteractionServices:
    """聊天交互和通用指令相关服务。"""

    chat: ChatInteractionService
    common: CommonCommandService
    help: HelpService
    music: MusicCommandService


@dataclass(frozen=True)
class CommunityServices:
    """成员、角色和目标解析相关服务。"""

    member: MemberService
    role: RoleService
    target_resolution: TargetResolutionService


@dataclass(frozen=True)
class SafetyServices:
    """风控、撤回和消息查询相关服务。"""

    moderation: ModerationService
    profanity: ProfanityGuardService
    recall: RecallService
    message_lookup: MessageLookupService
    recall_scheduler: MessageRecallScheduler


@dataclass(frozen=True)
class PluginServices:
    """插件相关服务。"""

    management: PluginManagementService


@dataclass(frozen=True)
class CommandServiceRegistry:
    """收拢命令处理链路涉及的服务分组。"""

    routing: RoutingServices
    interaction: InteractionServices
    community: CommunityServices
    safety: SafetyServices
    plugins: PluginServices


def build_command_service_registry(
    handler: "CommandHandler",
    *,
    bot_uid: str,
    bot_mention: str,
) -> CommandServiceRegistry:
    """构建命令处理链路所需的所有服务。"""
    access_service = CommandAccessService(handler, bot_mention=bot_mention)
    message_service = CommandMessageService(handler, bot_uid=bot_uid, bot_mention=bot_mention)
    command_router = CommandRouter(handler, bot_mention=bot_mention)
    mention_router = MentionCommandRouter(handler)
    slash_router = SlashCommandRouter(handler)
    chat_interaction = ChatInteractionService(handler)
    common_command = CommonCommandService(handler)
    help_service = HelpService(handler)
    music_command = MusicCommandService(handler)
    member_service = MemberService(handler)
    role_service = RoleService(handler)
    target_resolution = TargetResolutionService(handler)
    moderation_service = ModerationService(handler)
    profanity_guard = ProfanityGuardService(handler)
    recall_service = RecallService(handler)
    message_lookup = MessageLookupService(handler)
    recall_scheduler = MessageRecallScheduler(handler)
    plugin_management = PluginManagementService(handler)

    return CommandServiceRegistry(
        routing=RoutingServices(
            access=access_service,
            message=message_service,
            command=command_router,
            mention=mention_router,
            slash=slash_router,
        ),
        interaction=InteractionServices(
            chat=chat_interaction,
            common=common_command,
            help=help_service,
            music=music_command,
        ),
        community=CommunityServices(
            member=member_service,
            role=role_service,
            target_resolution=target_resolution,
        ),
        safety=SafetyServices(
            moderation=moderation_service,
            profanity=profanity_guard,
            recall=recall_service,
            message_lookup=message_lookup,
            recall_scheduler=recall_scheduler,
        ),
        plugins=PluginServices(
            management=plugin_management,
        ),
    )
