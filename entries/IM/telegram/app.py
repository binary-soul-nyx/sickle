from __future__ import annotations

from typing import Any

from sickle.config import AppConfig
from sickle.host import Sickle

from .handlers import handle_callback_query, handle_command, handle_text_message


def build_application(config: AppConfig, sickle: Sickle) -> Any:
    try:
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            CommandHandler,
            MessageHandler,
            filters,
        )
    except ImportError as exc:
        raise RuntimeError(
            "python-telegram-bot is required for Telegram entry",
        ) from exc

    if not config.telegram.bot_token:
        raise RuntimeError("telegram.bot_token is required")

    application = Application.builder().token(config.telegram.bot_token).build()
    application.bot_data["sickle"] = sickle

    command_names = ["start", "cancel", "clear", "agents", "reload", "mode", "help"]
    application.add_handler(CommandHandler(command_names, handle_command))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    return application
