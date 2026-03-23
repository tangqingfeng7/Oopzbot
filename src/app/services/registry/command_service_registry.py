from dataclasses import dataclass

from app.services.community.member_service import MemberService
from app.services.community.role_service import RoleService
from app.services.community.target_resolution_service import TargetResolutionService
from app.services.interaction.chat_interaction_service import ChatInteractionService
from app.services.interaction.common_command_service import CommonCommandService
from app.services.interaction.help_service import HelpService
from app.services.interaction.music_command_service import MusicCommandService
from app.services.interaction.selection_service import SelectionService
from app.services.interaction.setup_service import SetupService
from app.services.plugins.plugin_management_service import PluginManagementService
from app.services.routing.command_access_service import CommandAccessService
from app.services.routing.command_message_service import CommandMessageService
from app.services.routing.command_router import CommandRouter
from app.services.routing.mention_command_router import MentionCommandRouter
from app.services.routing.slash_command_router import SlashCommandRouter
from app.services.runtime import CommandRuntimeView
from app.services.safety.message_lookup_service import MessageLookupService
from app.services.safety.message_recall_scheduler import MessageRecallScheduler
from app.services.safety.moderation_service import ModerationService
from app.services.safety.profanity_guard_service import ProfanityGuardService
from app.services.safety.recall_service import RecallService
from scheduler_service import ReminderService, ScheduledMessageService


@dataclass(frozen=True)
class RoutingServices:
    access: CommandAccessService
    message: CommandMessageService
    command: CommandRouter
    mention: MentionCommandRouter
    slash: SlashCommandRouter


@dataclass(frozen=True)
class InteractionServices:
    chat: ChatInteractionService
    common: CommonCommandService
    help: HelpService
    music: MusicCommandService
    selection: SelectionService
    setup: SetupService


@dataclass(frozen=True)
class CommunityServices:
    member: MemberService
    role: RoleService
    target_resolution: TargetResolutionService


@dataclass(frozen=True)
class SafetyServices:
    moderation: ModerationService
    profanity: ProfanityGuardService
    recall: RecallService
    message_lookup: MessageLookupService
    recall_scheduler: MessageRecallScheduler


@dataclass(frozen=True)
class PluginServices:
    management: PluginManagementService


@dataclass(frozen=True)
class SchedulerServices:
    scheduled: ScheduledMessageService
    reminder: ReminderService


@dataclass(frozen=True)
class CommandServiceRegistry:
    routing: RoutingServices
    interaction: InteractionServices
    community: CommunityServices
    safety: SafetyServices
    plugins: PluginServices
    scheduler: SchedulerServices


def _build_routing_services(runtime: CommandRuntimeView) -> RoutingServices:
    return RoutingServices(
        access=CommandAccessService(runtime),
        message=CommandMessageService(runtime),
        command=CommandRouter(runtime),
        mention=MentionCommandRouter(runtime),
        slash=SlashCommandRouter(runtime),
    )


def _build_interaction_services(runtime: CommandRuntimeView) -> InteractionServices:
    return InteractionServices(
        chat=ChatInteractionService(runtime),
        common=CommonCommandService(runtime),
        help=HelpService(runtime),
        music=MusicCommandService(runtime),
        selection=SelectionService(),
        setup=SetupService(runtime),
    )


def _build_community_services(runtime: CommandRuntimeView) -> CommunityServices:
    return CommunityServices(
        member=MemberService(runtime),
        role=RoleService(runtime),
        target_resolution=TargetResolutionService(runtime),
    )


def _build_safety_services(runtime: CommandRuntimeView) -> SafetyServices:
    return SafetyServices(
        moderation=ModerationService(runtime),
        profanity=ProfanityGuardService(runtime),
        recall=RecallService(runtime),
        message_lookup=MessageLookupService(runtime),
        recall_scheduler=MessageRecallScheduler(runtime),
    )


def _build_plugin_services(runtime: CommandRuntimeView) -> PluginServices:
    return PluginServices(
        management=PluginManagementService(runtime),
    )


def _build_scheduler_services(runtime: CommandRuntimeView) -> SchedulerServices:
    try:
        from config import SCHEDULER_CONFIG
    except ImportError:
        SCHEDULER_CONFIG = {}
    try:
        from config import REMINDER_CONFIG
    except ImportError:
        REMINDER_CONFIG = {}

    sender = runtime.infrastructure.sender
    scheduled_svc = ScheduledMessageService(
        sender=sender,
        interval=int(SCHEDULER_CONFIG.get("check_interval_seconds", 30) if SCHEDULER_CONFIG else 30),
    )
    reminder_svc = ReminderService(
        sender=sender,
        interval=int(REMINDER_CONFIG.get("check_interval_seconds", 15) if REMINDER_CONFIG else 15),
        max_per_user=int(REMINDER_CONFIG.get("max_per_user", 5) if REMINDER_CONFIG else 5),
        max_delay_hours=int(REMINDER_CONFIG.get("max_delay_hours", 72) if REMINDER_CONFIG else 72),
    )
    return SchedulerServices(scheduled=scheduled_svc, reminder=reminder_svc)


def build_command_service_registry(runtime: CommandRuntimeView) -> CommandServiceRegistry:
    return CommandServiceRegistry(
        routing=_build_routing_services(runtime),
        interaction=_build_interaction_services(runtime),
        community=_build_community_services(runtime),
        safety=_build_safety_services(runtime),
        plugins=_build_plugin_services(runtime),
        scheduler=_build_scheduler_services(runtime),
    )
