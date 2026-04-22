from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from sickle.route.response import Button, Response

TELEGRAM_MAX_TEXT_LENGTH = 4096


async def render_response(update: Any, context: Any, response: Response) -> None:
    if response.is_empty():
        return

    chat_id = _extract_chat_id(update)
    if chat_id is None:
        return

    reply_markup = _build_reply_markup(response.buttons)
    for chunk in _split_text(response.text):
        await context.bot.send_message(
            chat_id=chat_id,
            text=chunk,
            disable_notification=response.silent,
            reply_markup=reply_markup,
        )
        reply_markup = None

    for file_path in response.files:
        await _send_file(context, chat_id, file_path, response.silent)


def _extract_chat_id(update: Any) -> int | None:
    chat = getattr(update, "effective_chat", None)
    if chat is not None:
        return getattr(chat, "id", None)
    return None


def _split_text(text: str | None) -> Iterable[str]:
    if not text:
        return []

    chunks: list[str] = []
    for start in range(0, len(text), TELEGRAM_MAX_TEXT_LENGTH):
        chunks.append(text[start : start + TELEGRAM_MAX_TEXT_LENGTH])
    return chunks


def _build_reply_markup(buttons: list[list[Button]]) -> Any | None:
    if not buttons:
        return None

    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    except ImportError:
        return None

    keyboard: list[list[Any]] = []
    for row in buttons:
        keyboard_row: list[Any] = []
        for button in row:
            if button.url:
                keyboard_row.append(
                    InlineKeyboardButton(text=button.text, url=button.url),
                )
            else:
                keyboard_row.append(
                    InlineKeyboardButton(
                        text=button.text,
                        callback_data=button.callback_id,
                    ),
                )
        keyboard.append(keyboard_row)
    return InlineKeyboardMarkup(keyboard)


async def _send_file(context: Any, chat_id: int, file_path: Path, silent: bool) -> None:
    if not file_path.exists():
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"[missing file] {file_path}",
            disable_notification=silent,
        )
        return

    with file_path.open("rb") as handle:
        await context.bot.send_document(
            chat_id=chat_id,
            document=handle,
            disable_notification=silent,
        )
