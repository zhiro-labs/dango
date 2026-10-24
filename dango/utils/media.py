"""
Download Discord image attachments and stickers as Agno Image objects.

Shared by the history step (past messages) and the LLM step (current message).
Downloads are best-effort: a failed one is logged and skipped.
"""

import aiohttp
from agno.media import Image

# Sticker format → image mime type. Lottie (Discord's default packs) is vector
# JSON, not viewable by vision models, so it is intentionally absent here.
STICKER_IMAGE_MIME = {
    "png":  "image/png",
    "apng": "image/png",
    "gif":  "image/gif",
}


def sticker_mime(format_name: str | None) -> str | None:
    """Image mime type for a sticker format name, or None if not viewable."""
    return STICKER_IMAGE_MIME.get((format_name or "").lower())


def is_model_image(filename: str, content_type: str | None) -> bool:
    """True for image attachments the model should see.

    dango_replaced_* files are the bot's own rendered tables; their markdown
    is restored into the text instead.
    """
    return "dango_replaced" not in filename and (content_type or "").startswith("image/")


async def fetch_image(
    session: aiohttp.ClientSession, url: str, mime_type: str, log_tag: str, what: str = "image"
) -> Image | None:
    """GET url and wrap the body as an Image; None on any failure."""
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                return Image(content=await resp.read(), mime_type=mime_type)
    except Exception as e:
        print(f"❌ [{log_tag}] Failed to download {what}: {e}")
    return None


async def download_attachment_images(attachments: list[dict], log_tag: str) -> list[Image]:
    """Download image attachments given as message_data dicts."""
    images: list[Image] = []
    async with aiohttp.ClientSession() as session:
        for att in attachments:
            content_type = att.get("content_type", "")
            if not is_model_image(att.get("filename", ""), content_type):
                continue
            image = await fetch_image(session, att["url"], content_type, log_tag)
            if image:
                images.append(image)
    return images


async def download_sticker_images(stickers: list[dict], log_tag: str) -> tuple[list[Image], list[str]]:
    """Download stickers given as message_data dicts.

    Returns (images, names). Every sticker's name is returned regardless of
    format, so Lottie stickers still reach the model as text.
    """
    images: list[Image] = []
    names: list[str] = []
    if not stickers:
        return images, names
    async with aiohttp.ClientSession() as session:
        for st in stickers:
            name = st.get("name", "")
            if name:
                names.append(name)
            mime = sticker_mime(st.get("format"))
            if not mime:
                continue
            image = await fetch_image(session, st["url"], mime, log_tag, what="sticker")
            if image:
                images.append(image)
    return images, names
