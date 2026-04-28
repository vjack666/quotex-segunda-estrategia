from __future__ import annotations

from typing import List


def _clip(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def render_box(title: str, lines: List[str], width: int, height: int) -> List[str]:
    inner = max(1, width - 2)
    content_height = max(1, height - 2)

    top_title = f" {title} "
    top = "+" + _clip(top_title.ljust(inner, "-"), inner) + "+"

    body: List[str] = []
    for i in range(content_height):
        line = lines[i] if i < len(lines) else ""
        body.append("|" + _clip(line, inner).ljust(inner) + "|")

    bottom = "+" + ("-" * inner) + "+"
    return [top, *body, bottom]


def hstack(boxes: List[List[str]], gap: int = 1) -> List[str]:
    if not boxes:
        return []
    height = len(boxes[0])
    sep = " " * gap
    result: List[str] = []
    for row in range(height):
        parts = [b[row] for b in boxes]
        result.append(sep.join(parts))
    return result


def framed(title: str, lines: List[str], width: int) -> str:
    header = "+" + title.center(width - 2, "=") + "+"
    footer = "+" + ("=" * (width - 2)) + "+"
    body = ["|" + ln.ljust(width - 2)[: width - 2] + "|" for ln in lines]
    return "\n".join([header, *body, footer])
