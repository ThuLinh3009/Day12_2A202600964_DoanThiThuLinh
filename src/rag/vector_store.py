from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb

from rag.parser import parse_policy_markdown


class ChromaPolicyStore:
    """Chroma-backed policy index using sentence-transformer embeddings."""

    def __init__(
        self,
        persist_directory: Path,
        embedding_model: Any,
        collection_name: str = "policy_chunks",
    ) -> None:
        persist_directory.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_directory))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._embedder = embedding_model

    def ensure_index(self, markdown_path: Path) -> None:
        if self._collection.count() == 0:
            self.rebuild(markdown_path)

    def rebuild(self, markdown_path: Path) -> None:
        text = markdown_path.read_text(encoding="utf-8")
        chunks = parse_policy_markdown(text)

        if not chunks:
            return

        # Delete existing docs and re-add
        existing = self._collection.get(include=[])
        if existing["ids"]:
            self._collection.delete(ids=existing["ids"])

        ids = [f"chunk_{i}" for i in range(len(chunks))]
        documents = [c["rendered_text"] for c in chunks]
        metadatas = [
            {
                "section_h2": c["section_h2"],
                "section_h3": c["section_h3"],
                "citation": c["citation"],
            }
            for c in chunks
        ]
        embeddings = self._embedder.embed_documents(documents)

        self._collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def search(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        query_embedding = self._embedder.embed_query(query)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        hits = []
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]
        for doc, meta, dist in zip(docs, metas, dists):
            hits.append({
                "citation": meta.get("citation", ""),
                "section_h2": meta.get("section_h2", ""),
                "section_h3": meta.get("section_h3", ""),
                "content": doc,
                "distance": dist,
            })
        return hits
