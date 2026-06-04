"""
Extract markdown tables from LLM response and render them as PNG images.
Combines the original MarkdownTableExtractor + TableImageRenderer nodes.
"""

import io
import os
import re
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from agno.workflow import StepInput, StepOutput


async def extract_and_render_tables(step_input: StepInput) -> StepOutput:
    """Extract markdown tables from response text and render each as a PNG image."""
    data = step_input.previous_step_content

    if data.get("error"):
        return StepOutput(content=data)

    llm_response = data.get("llm_response", "")
    message_data = data["message_data"]
    message_id = message_data.get("message_id") or message_data.get("channel_id", "0")

    print("📊 [extract_and_render_tables] Extracting tables from LLM response")

    table_pattern = r"(\|[^\n]*\|\s*\n\|[-\s|:]*\|\s*\n(?:\|[^\n]*\|\s*\n?)*)"
    tables = re.findall(table_pattern, llm_response, re.MULTILINE)

    if not tables:
        print("📊 [extract_and_render_tables] No tables found")
        return StepOutput(
            content={
                "response_text": llm_response,
                "table_images": [],
                "extracted_tables_files": [],
                "message_data": message_data,
                "fallback_sysinfo": data.get("fallback_sysinfo"),
                "ephemeral": data.get("ephemeral", False),
            }
        )

    print(f"✅ [extract_and_render_tables] Found {len(tables)} table(s)")
    os.makedirs("temp", exist_ok=True)

    rendered_images = []
    extracted_files = []
    response_text = llm_response

    for i, table_text in enumerate(tables):
        table_text = table_text.strip()
        table_count = i + 1
        parsed = _parse_table(table_text)

        filename = f"temp/dango_replaced_table_{message_id}_{table_count}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(table_text)
        extracted_files.append(filename)

        if parsed["valid"]:
            try:
                buffer = _render_table_image(parsed)
                rendered_images.append(
                    {
                        "index": i,
                        "buffer": buffer,
                        "filename": f"table_{table_count}.png",
                    }
                )
                placeholder = f"> `[dango_replaced_table_{message_id}_{table_count}_as_image]`"
                response_text = response_text.replace(table_text, placeholder)
                print(
                    f"✅ [extract_and_render_tables] Rendered table {table_count}"
                )
            except Exception as e:
                print(
                    f"❌ [extract_and_render_tables] Failed to render table {table_count}: {e}"
                )
        else:
            print(
                f"⚠️ [extract_and_render_tables] Skipping invalid table {table_count}"
            )

    response_text = re.sub(r"\n\s*\n\s*\n", "\n\n", response_text).strip()

    return StepOutput(
        content={
            "response_text": response_text,
            "table_images": rendered_images,
            "extracted_tables_files": extracted_files,
            "message_data": message_data,
            "fallback_sysinfo": data.get("fallback_sysinfo"),
            "ephemeral": data.get("ephemeral", False),
        }
    )


def _parse_table(table_text: str) -> dict[str, Any]:
    lines = [l.strip() for l in table_text.split("\n") if l.strip()]
    if len(lines) < 3:
        return {"headers": [], "rows": [], "valid": False}
    headers = [c.strip() for c in lines[0].split("|")[1:-1]]
    rows = []
    for line in lines[2:]:
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            while len(cells) < len(headers):
                cells.append("")
            rows.append(cells[: len(headers)])
    return {"headers": headers, "rows": rows, "valid": len(headers) > 0 and len(rows) > 0}


def _get_font(size: int, bold: bool = False):
    try:
        path = (
            "assets/fonts/03_NotoSansCJK-OTC/NotoSansCJK-Bold.ttc"
            if bold
            else "assets/fonts/03_NotoSansCJK-OTC/NotoSansCJK-Regular.ttc"
        )
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.truetype("assets/fonts/NotoSansCJK.ttc", size)
        except Exception:
            return ImageFont.load_default()


def _parse_text_formatting(text: str):
    segments = []
    parts = re.split(r"(\*\*[^*]*?\*\*|\*\*[^*]*$|^[^*]*\*\*|\*\*[^*]*)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            segments.append(("bold", part[2:-2]))
        elif part.startswith("**") and len(part) > 2:
            segments.append(("bold", part[2:]))
        elif part.endswith("**") and len(part) > 2:
            segments.append(("bold", part[:-2]))
        elif "**" in part:
            subparts = part.split("**")
            for idx, subpart in enumerate(subparts):
                if subpart:
                    segments.append(("bold" if idx % 2 == 1 else "regular", subpart))
        else:
            segments.append(("regular", part))
    return segments


def _wrap_text_with_formatting(text: str, max_width: int, fonts: dict) -> list:
    if not text:
        return [[("regular", "")]]
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    segments = _parse_text_formatting(text)
    lines, current_line, current_width = [], [], 0
    for segment_type, segment_text in segments:
        font = fonts["cell_bold"] if segment_type == "bold" else fonts["cell"]
        for word in segment_text.split():
            word_width = draw.textlength(word, font=font)
            space_width = draw.textlength(" ", font=font)
            space_needed = space_width if current_line else 0
            if current_width + word_width + space_needed <= max_width:
                current_line.append((segment_type, word))
                current_width += word_width + space_width
            else:
                if current_line:
                    lines.append(current_line)
                if word_width > max_width:
                    chunk = ""
                    for char in word:
                        if draw.textlength(chunk + char, font=font) <= max_width:
                            chunk += char
                        else:
                            if chunk:
                                lines.append([(segment_type, chunk)])
                            chunk = char
                    if chunk:
                        current_line = [(segment_type, chunk)]
                        current_width = draw.textlength(chunk, font=font) + space_width
                else:
                    current_line = [(segment_type, word)]
                    current_width = word_width + space_width
    if current_line:
        lines.append(current_line)
    return lines or [[("regular", "")]]


def _calc_col_widths(headers, rows, font, padding=36):
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    col_widths = []
    for i, header in enumerate(headers):
        max_w = max(360, int(draw.textlength(header, font=font)) + padding * 2)
        for row in rows:
            if i < len(row):
                text_w = int(draw.textlength(str(row[i]).strip(), font=font)) + padding * 2
                max_w = max(max_w, min(text_w, 1200))
        col_widths.append(max_w)
    return col_widths


def _render_table_image(table_data: dict[str, Any]) -> io.BytesIO:
    headers, rows = table_data["headers"], table_data["rows"]
    if not headers:
        raise ValueError("Table must have at least one header")

    font_size = 42
    fonts = {
        "header": _get_font(font_size + 6, bold=False),
        "header_bold": _get_font(font_size + 6, bold=True),
        "cell": _get_font(font_size, bold=False),
        "cell_bold": _get_font(font_size, bold=True),
        "line_height": font_size + 12,
    }
    colors = {
        "bg": (255, 255, 255),
        "header_bg": (230, 230, 230),
        "row_bg": (255, 255, 255),
        "row_bg_alt": (248, 248, 248),
        "border": (200, 200, 200),
        "text": (0, 0, 0),
        "header_text": (20, 20, 20),
    }
    padding, header_height, min_cell_height = 36, 120, 84
    col_widths = _calc_col_widths(headers, rows, fonts["cell"], padding)

    processed_data = []
    for row in rows:
        processed_row, row_height = [], min_cell_height
        for i, cell in enumerate(row):
            wrapped = _wrap_text_with_formatting(
                str(cell).strip(), col_widths[i] - padding * 2, fonts
            )
            processed_row.append(wrapped)
            row_height = max(row_height, len(wrapped) * fonts["line_height"] + padding)
        processed_data.append((processed_row, row_height))

    total_width = sum(col_widths) + len(col_widths) + 1
    total_height = (
        header_height + sum(h for _, h in processed_data) + len(processed_data) + 1
    )
    img = Image.new("RGB", (total_width, total_height), colors["bg"])
    draw = ImageDraw.Draw(img)

    # Draw header row
    x = 0
    for header, width in zip(headers, col_widths):
        draw.rectangle([x, 0, x + width, header_height], fill=colors["header_bg"], outline=colors["border"])
        header_lines = _wrap_text_with_formatting(header, width - padding * 2, fonts)
        total_text_h = len(header_lines) * fonts["line_height"]
        text_y = (header_height - total_text_h) // 2
        for line_segs in header_lines:
            line_width = sum(
                draw.textlength(w, font=fonts["header_bold" if t == "bold" else "header"]) for t, w in line_segs
            )
            current_x = x + (width - line_width) // 2
            for idx, (seg_type, word) in enumerate(line_segs):
                font = fonts["header_bold" if seg_type == "bold" else "header"]
                if idx > 0:
                    draw.text((current_x, text_y), " ", fill=colors["header_text"], font=font)
                    current_x += draw.textlength(" ", font=font)
                draw.text((current_x, text_y), word, fill=colors["header_text"], font=font)
                current_x += draw.textlength(word, font=font)
            text_y += fonts["line_height"]
        x += width + 1

    # Draw data rows
    y = header_height + 1
    for row_idx, (processed_row, row_height) in enumerate(processed_data):
        x = 0
        row_bg = colors["row_bg_alt"] if row_idx % 2 else colors["row_bg"]
        for wrapped_lines, width in zip(processed_row, col_widths):
            draw.rectangle([x, y, x + width, y + row_height], fill=row_bg, outline=colors["border"])
            text_x, text_y = x + padding, y + padding // 2
            for line_segs in wrapped_lines:
                if text_y + fonts["line_height"] <= y + row_height - padding // 2:
                    current_x = text_x
                    for idx, (seg_type, word) in enumerate(line_segs):
                        font = fonts["cell_bold" if seg_type == "bold" else "cell"]
                        if idx > 0:
                            draw.text((current_x, text_y), " ", fill=colors["text"], font=font)
                            current_x += draw.textlength(" ", font=font)
                        draw.text((current_x, text_y), word, fill=colors["text"], font=font)
                        current_x += draw.textlength(word, font=font)
                    text_y += fonts["line_height"]
            x += width + 1
        y += row_height + 1

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", quality=100, optimize=False, dpi=(300, 300))
    buffer.seek(0)
    return buffer
