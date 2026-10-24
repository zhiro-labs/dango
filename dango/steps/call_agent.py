"""
LLMChat step: run the agent for one Discord message.

Builds the current user turn (mentions, images, stickers), routes it to the
fast or deep agent, trims history to that model's token budget, runs it with
retry and fallback, and shapes the result for the next step.

Agents, models and tools live in dango.agent and are created once;
per-request context is passed via session_state.
"""

from agno.models.message import Message
from agno.run.base import RunStatus
from agno.workflow import StepInput, StepOutput

from ..agent import choose_route, get_agents, run_with_fallback, trim_to_token_budget
from ..extensions.context import reset_request_context, set_request_context
from ..utils.discord_helpers import format_sysinfo, resolve_mentions
from ..utils.media import download_attachment_images, download_sticker_images

_LOG_TAG = "call_discord_agent"


async def _current_turn(message_data: dict, mention_map: dict[str, str]) -> tuple[str, Message]:
    """Return (content, user Message) for the message being answered.

    `content` is the text without the author prefix; routing classifies it.
    """
    content = resolve_mentions(message_data["content"], mention_map)
    images = await download_attachment_images(message_data.get("attachments", []), log_tag=_LOG_TAG)

    # Stickers: append the downloaded images and note their names in text, so the
    # model knows the image is a sticker (and still gets the name for Lottie ones).
    sticker_images, sticker_names = await download_sticker_images(
        message_data.get("stickers", []), log_tag=_LOG_TAG
    )
    images.extend(sticker_images)
    if sticker_names:
        note = f"[sticker: {', '.join(sticker_names)}]"
        content = f"{content} {note}" if content else note

    message = Message(
        role="user",
        content=f"{message_data['author_name']}: {content}",
        images=images or None,
    )
    return content, message


def _session_state(message_data: dict, unique_users: set[str]) -> dict:
    """Per-request context read by the instructions callable and custom tools."""
    return {
        "author_name":  message_data["author_name"],
        "author_id":    message_data.get("author_id"),
        "unique_users": list(unique_users),
        "chat_sys_prompt": message_data["_chat_sys_prompt"],
        "history_limit": message_data.get("_history_limit"),
        "timezone":     message_data.get("_timezone"),
        "channel_id":   message_data.get("channel_id"),
        "channel_name": message_data.get("channel_name", ""),
        "guild_id":     message_data.get("guild_id"),
        "guild_name":   message_data.get("guild_name", ""),
        "author_permissions": message_data.get("author_permissions", []),
        "mentioned_users":    message_data.get("mentioned_users", []),
        "mentioned_roles":    message_data.get("mentioned_roles", []),
        "forced_skill":       message_data.get("_force_skill"),
    }


async def call_discord_agent(step_input: StepInput) -> StepOutput:
    """Run the Discord agent with per-request context injected via session_state."""
    agents = get_agents()
    data = step_input.previous_step_content

    if data.get("error"):
        return StepOutput(content=data)

    message_data = data["message_data"]
    history: list[Message] = data["formatted_history"]

    content, user_message = await _current_turn(message_data, data.get("mention_map") or {})
    messages = list(history) + [user_message]

    route = choose_route(
        agents,
        content,
        history=[m.content for m in history if isinstance(m.content, str) and m.content],
        force_deep=bool(message_data.get("_force_deep")),
    )

    budget = route.spec.context_budget
    if budget:
        before = len(messages)
        messages = trim_to_token_budget(messages, budget, model_id=route.spec.model_id)
        trimmed = before - len(messages)
        if trimmed:
            print(f"✂️ [call_discord_agent] Trimmed {trimmed} messages to fit token budget ({budget})")

    print(f"🤖 [call_discord_agent] Sending {len(messages)} messages to {route.spec.name}")

    session_state = _session_state(message_data, set(data.get("unique_users", [])))

    # Expose per-request context to custom agent tools (custom/*.py) for the
    # duration of the agent run, so a tool's Ctx.from_agent() sees who/where.
    ctx_token = set_request_context(session_state)
    try:
        response, fallback = await run_with_fallback(agents, route, messages, session_state)
    finally:
        reset_request_context(ctx_token)

    if response.status == RunStatus.error:
        tried = f"{route.spec.name} and {fallback.name}" if fallback else route.spec.name
        print(f"❌ [call_discord_agent] All models failed ({tried})")
        error_detail = (response.content or "").strip() or None
        body = f"⚠️ The model is currently overloaded ({tried} unavailable). Please try again later."
        if error_detail:
            body += f"\n{error_detail}"
        return StepOutput(
            content={
                "error": True,
                "error_message": format_sysinfo(body),
                "message_data": message_data,
            }
        )

    llm_response = response.content or ""
    print(f"📥 [call_discord_agent] Received response ({len(llm_response)} chars)")

    return StepOutput(
        content={
            "llm_response": llm_response,
            "message_data": message_data,
            "fallback_sysinfo": (
                format_sysinfo(f"⚡ {route.spec.name} failed — response served by {fallback.name}.")
                if fallback else None
            ),
        }
    )
