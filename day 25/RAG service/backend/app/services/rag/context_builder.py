"""Context Builder: собирает контекст для LLM из финальных чанков.

Формат каждого блока строго задан: chunk_id, source, section и текст.
LLM видит только chunk_id — источники и цитаты формирует backend.
"""

from __future__ import annotations

from typing import Dict, List


def build_context(chunks: List[Dict]) -> str:
    parts: List[str] = []
    for it in chunks:
        cid = it.get("chunk_id", "")
        src = it.get("source", "")
        sec = it.get("section") or ""
        text = (it.get("text") or "").strip()
        header = f"[chunk_id={cid}]\nsource={src}"
        if sec:
            header += f"\nsection={sec}"
        parts.append(f"{header}\n{text}")
    return "\n\n".join(parts)
