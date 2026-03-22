from area_join_notifier import start_area_join_notifier
from command_handler import CommandHandler
from oopz_client import OopzClient
from oopz_sender import OopzSender

from app.lifecycle.context import AppContext


class AppContextBuilder:
    """负责组装启动期使用的应用上下文。"""

    def build(self, sender: OopzSender, voice=None) -> AppContext:
        notifier_callback = start_area_join_notifier(sender=sender)
        handler = CommandHandler(sender, voice_client=voice)

        client = OopzClient(
            on_chat_message=handler.handle_message,
            on_other_event=notifier_callback,
        )
        return AppContext(
            sender=sender,
            handler=handler,
            client=client,
            notifier_callback=notifier_callback,
            voice=voice,
        )
