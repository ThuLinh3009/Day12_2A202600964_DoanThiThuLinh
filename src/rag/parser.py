from __future__ import annotations

import re


def parse_policy_markdown(markdown_text: str) -> list[dict]:
    """Parse policy markdown into chunks by H2 > H3 structure.

    Each chunk contains:
    - section_h2: H2 heading text
    - section_h3: H3 heading text (empty string if content is directly under H2)
    - citation: e.g. "4.3. Thời gian giao hàng dự kiến"
    - rendered_text: full H2 + H3 + body text for embedding
    """
    chunks: list[dict] = []
    lines = markdown_text.splitlines()

    current_h2 = ""
    current_h3 = ""
    buffer: list[str] = []

    def flush(h2: str, h3: str, body_lines: list[str]) -> None:
        body = "\n".join(body_lines).strip()
        if not body:
            return
        citation = h3 if h3 else h2
        # Strip leading ## / ### from citation
        citation = re.sub(r"^#+\s*", "", citation).strip()
        rendered = f"{h2}\n{h3}\n{body}".strip() if h3 else f"{h2}\n{body}".strip()
        chunks.append({
            "section_h2": re.sub(r"^#+\s*", "", h2).strip(),
            "section_h3": re.sub(r"^#+\s*", "", h3).strip(),
            "citation": citation,
            "rendered_text": rendered,
        })

    for line in lines:
        if line.startswith("## "):
            flush(current_h2, current_h3, buffer)
            current_h2 = line.strip()
            current_h3 = ""
            buffer = []
        elif line.startswith("### "):
            flush(current_h2, current_h3, buffer)
            current_h3 = line.strip()
            buffer = []
        else:
            buffer.append(line)

    flush(current_h2, current_h3, buffer)
    return chunks
