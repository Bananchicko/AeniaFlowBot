"""Paginate the complete local legal text within photo caption limits."""

import re


def plain_legal(source):
    text = re.sub(r"^#{1,6}\s+", "", source, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    return text.replace("**", "").replace("`", "").strip()


def split_pages(text, limit=780):
    pages = []
    while text:
        used, end = 0, 0
        for char in text:
            cost = len(char.encode("utf-16-le")) // 2
            if used + cost > limit:
                break
            used += cost
            end += 1
        if end < len(text):
            boundary = max(text.rfind("\n", 0, end), text.rfind(" ", 0, end))
            if boundary > end // 2:
                end = boundary
        pages.append(text[:end].strip())
        text = text[end:].lstrip()
    return pages or [""]
