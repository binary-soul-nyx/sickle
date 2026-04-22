from __future__ import annotations

from typing import Any

from sickle.route.response import Response

from .renderer import render_response


def _get_sickle(context: Any) -> Any:
    sickle = context.application.bot_data.get("sickle")
    if sickle is None:
        raise RuntimeError("Sickle instance not found in bot_data")
    return sickle


async def handle_text_message(update: Any, context: Any) -> None:
    message = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    if message is None or user is None:
        return

    text = getattr(message, "text", "") or ""
    sickle = _get_sickle(context)
    response = await sickle.handle_message(user.id, text)
    await render_response(update, context, response)


async def handle_command(update: Any, context: Any) -> None:
    message = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    if message is None or user is None:
        return

    raw = (getattr(message, "text", "") or "").strip()
    if not raw.startswith("/"):
        return

    command_text = raw[1:]
    token, _, raw_args = command_text.partition(" ")
    cmd = token.split("@", maxsplit=1)[0].lower()
    args = raw_args.split() if raw_args else []

    if cmd == "start":
        response = await _handle_start(update, context)
    else:
        sickle = _get_sickle(context)
        response = await sickle.handle_command(user.id, cmd, args)
    await render_response(update, context, response)


async def handle_callback_query(update: Any, context: Any) -> None:
    query = getattr(update, "callback_query", None)
    user = getattr(update, "effective_user", None)
    if query is None or user is None:
        return

    await query.answer()
    callback_id = getattr(query, "data", "") or ""
    sickle = _get_sickle(context)
    response = await sickle.handle_button(user.id, callback_id)
    await render_response(update, context, response)


async def _handle_start(update: Any, context: Any) -> Any:
    sickle = _get_sickle(context)
    user = getattr(update, "effective_user", None)
    if user is None:
        return Response.empty()

    return await sickle.handle_command(user.id, "help", [])
