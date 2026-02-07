from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import re
from pypdf import PdfReader

from .config import SETTINGS

log = logging.getLogger("rag")


def _extract_pdf_text(path: Path) -> list[str]:
    try:
        reader = PdfReader(str(path))
    except Exception:
        log.exception("pdf_read_failed", extra={"path": str(path)})
        return []

    pages = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text:
            pages.append(text)
    return pages


def _chunk_text(text: str, max_len: int = 600) -> list[str]:
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    current = ""
    for part in parts:
        if len(current) + len(part) + 1 <= max_len:
            current = f"{current} {part}".strip()
        else:
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks


class FAQRetriever:
    def __init__(self, docs_dir: Path):
        self.docs_dir = docs_dir
        self.chunks: list[dict[str, Any]] = []
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.docs_dir.exists():
            log.warning("faq_dir_missing", extra={"path": str(self.docs_dir)})
            return

        docs: list[dict[str, Any]] = []
        for pdf in self.docs_dir.glob("*.pdf"):
            for page_text in _extract_pdf_text(pdf):
                for chunk in _chunk_text(page_text):
                    docs.append(
                        {
                            "text": chunk,
                            "source": pdf.name,
                            "tokens": self._tokenize(chunk),
                        }
                    )

        if not docs:
            return
        self.chunks = docs

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens = re.findall(r"[\\w]+", text.lower())
        return {t for t in tokens if t and len(t) > 1}

    def query(self, question: str, top_k: int = 3) -> list[dict[str, Any]]:
        self.load()
        if not self.chunks:
            return []
        query_tokens = self._tokenize(question)
        if not query_tokens:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in self.chunks:
            tokens = doc.get("tokens", set())
            if not tokens:
                continue
            overlap = len(query_tokens & tokens)
            if overlap == 0:
                continue
            score = overlap / max(len(query_tokens), 1)
            scored.append((score, doc))

        if not scored:
            return []
        scored.sort(key=lambda item: item[0], reverse=True)
        results = []
        for score, doc in scored[:top_k]:
            results.append({"score": score, "text": doc["text"], "source": doc["source"]})
        return results


_retriever: FAQRetriever | None = None


def get_retriever() -> FAQRetriever:
    global _retriever
    if _retriever is None:
        _retriever = FAQRetriever(SETTINGS.data_paths.faqs_dir)
    return _retriever
