"""
ARGUS AI — Retrieval-Augmented Generation Engine
"""

import asyncio
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from argus.ai.llm import OllamaClient

logger = logging.getLogger("ARGUS.AI.RAG")

# Optional ChromaDB import — import-safe
try:
    import chromadb
    from chromadb.config import Settings

    _CHROMA_AVAILABLE = True
except Exception:
    _CHROMA_AVAILABLE = False
    chromadb = None  # type: ignore

DEFAULT_COLLECTION = "argus_knowledge"


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class _InMemoryStore:
    """Fallback vector store when ChromaDB is unavailable."""

    def __init__(self):
        self.documents: List[str] = []
        self.metadatas: List[Dict[str, Any]] = []
        self.embeddings: List[List[float]] = []

    def add(self, docs: List[str], embeddings: List[List[float]], metadatas: List[Dict[str, Any]]):
        self.documents.extend(docs)
        self.embeddings.extend(embeddings)
        self.metadatas.extend(metadatas)

    def query(self, embedding: List[float], top_k: int = 5) -> Tuple[List[str], List[Dict[str, Any]], List[float]]:
        if not self.embeddings:
            return [], [], []
        scored = []
        for emb, doc, meta in zip(self.embeddings, self.documents, self.metadatas):
            sim = _cosine_similarity(embedding, emb)
            scored.append((sim, doc, meta))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]
        return [t[1] for t in top], [t[2] for t in top], [t[0] for t in top]


class RAGEngine:
    """
    Async RAG engine using Ollama for embeddings and generation.
    Falls back to an in-memory store if ChromaDB is unavailable.
    """

    def __init__(
        self,
        ollama: Optional[OllamaClient] = None,
        collection_name: str = DEFAULT_COLLECTION,
        chroma_path: Optional[str] = None,
    ):
        self.ollama = ollama or OllamaClient()
        self.collection_name = collection_name
        self._store: Optional[Any] = None
        self._chroma_collection: Optional[Any] = None
        self._in_memory: Optional[_InMemoryStore] = None
        self._chroma_path = chroma_path

    async def _init_store(self):
        if self._store is not None:
            return
        if _CHROMA_AVAILABLE:
            try:
                await asyncio.to_thread(self._init_chroma)
                logger.info("RAG using ChromaDB backend.")
                return
            except Exception as exc:
                logger.warning(f"ChromaDB init failed: {exc}. Falling back to in-memory store.")
        self._in_memory = _InMemoryStore()
        self._store = self._in_memory
        logger.info("RAG using in-memory fallback store.")

    def _init_chroma(self):
        # Synchronous Chroma init — runs in thread pool
        settings = Settings(anonymized_telemetry=False)
        if self._chroma_path:
            client = chromadb.PersistentClient(path=self._chroma_path, settings=settings)
        else:
            client = chromadb.Client(settings)
        self._chroma_collection = client.get_or_create_collection(name=self.collection_name)
        self._store = self._chroma_collection

    async def ingest_documents(
        self,
        docs: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Embed and store documents."""
        if not docs:
            return
        await self._init_store()
        metadatas = metadatas or [{} for _ in docs]
        if len(metadatas) != len(docs):
            raise ValueError("metadatas length must match docs length")

        # Generate embeddings in batches to avoid hammering Ollama
        embeddings: List[List[float]] = []
        for doc in docs:
            try:
                emb = await self.ollama.embed(doc)
                embeddings.append(emb)
            except Exception as exc:
                logger.error(f"Embedding failed for doc snippet: {exc}")
                embeddings.append([0.0] * 768)

        if self._chroma_collection is not None:
            ids = [f"doc_{i}" for i in range(len(docs))]
            try:
                await asyncio.to_thread(
                    self._chroma_collection.add,
                    ids=ids,
                    documents=docs,
                    metadatas=metadatas,
                    embeddings=embeddings,
                )
            except Exception as exc:
                logger.error(f"ChromaDB add failed: {exc}. Switching to in-memory.")
                if self._in_memory is None:
                    self._in_memory = _InMemoryStore()
                    self._store = self._in_memory
                self._in_memory.add(docs, embeddings, metadatas)
        else:
            self._in_memory.add(docs, embeddings, metadatas)

    async def query(
        self,
        question: str,
        top_k: int = 5,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Embed question, retrieve top-k docs, generate answer via Ollama.
        Returns structured response: {answer, sources, confidence}.
        """
        await self._init_store()

        # 1. Embed question
        try:
            q_emb = await self.ollama.embed(question)
        except Exception as exc:
            logger.error(f"Failed to embed question: {exc}")
            return {
                "answer": "I'm unable to process your question right now (embedding service unavailable).",
                "sources": [],
                "confidence": 0.0,
            }

        # 2. Retrieve documents
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []
        scores: List[float] = []
        try:
            if self._chroma_collection is not None:
                result = await asyncio.to_thread(
                    self._chroma_collection.query,
                    query_embeddings=[q_emb],
                    n_results=top_k,
                    include=["documents", "metadatas", "distances"],
                )
                docs = result.get("documents", [[]])[0] or []
                metas = result.get("metadatas", [[]])[0] or []
                distances = result.get("distances", [[]])[0] or []
                # Convert L2 distance to a rough similarity score (clipped)
                scores = [max(0.0, 1.0 - (d / 2.0)) for d in distances]
            else:
                docs, metas, scores = self._in_memory.query(q_emb, top_k=top_k)
        except Exception as exc:
            logger.error(f"Document retrieval failed: {exc}")

        # 3. Build context prompt
        if docs:
            context_blocks = []
            for i, (doc, meta) in enumerate(zip(docs, metas), start=1):
                source_tag = meta.get("source", f"doc_{i}")
                context_blocks.append(f"[Source {i} | {source_tag}]\n{doc}")
            context = "\n\n".join(context_blocks)
            prompt = (
                "Use the following retrieved sources to answer the question. "
                "If the sources do not contain enough information, say so.\n\n"
                f"--- Context ---\n{context}\n\n"
                f"Question: {question}\n\nAnswer:"
            )
        else:
            prompt = (
                f"Question: {question}\n\n"
                "No relevant documents were found in the knowledge base. "
                "Answer based on general knowledge if possible, otherwise state that you don't know.\n\nAnswer:"
            )

        # 4. Generate answer
        gen = await self.ollama.generate(prompt=prompt, system=system_prompt)
        answer = gen.get("response", "").strip()
        error = gen.get("error")
        if error:
            logger.warning(f"Ollama generation error: {error}")
            if not answer:
                answer = "I'm unable to generate an answer right now (LLM service unavailable)."

        # 5. Compute confidence from retrieval scores + generation presence
        confidence = 0.0
        if scores:
            confidence = float(min(1.0, sum(scores) / len(scores)))
        if not answer or "don't know" in answer.lower() or "unable" in answer.lower():
            confidence *= 0.5

        sources = []
        for doc, meta, score in zip(docs, metas, scores):
            sources.append({
                "content": doc[:500] + "..." if len(doc) > 500 else doc,
                "metadata": meta,
                "score": round(score, 4),
            })

        return {
            "answer": answer,
            "sources": sources,
            "confidence": round(confidence, 4),
        }

    async def chat(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        RAG-aware chat that includes optional conversation history.
        Returns {answer, sources, confidence}.
        """
        history = history or []
        # Build a condensed history string for the prompt
        history_lines = []
        for turn in history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            history_lines.append(f"{role.capitalize()}: {content}")
        history_str = "\n".join(history_lines)

        # Run RAG query with a system prompt that includes history awareness
        system = (
            "You are ARGUS, a tactical freight-intelligence assistant. "
            "Use the provided sources to answer accurately and concisely."
        )
        if history_str:
            system += "\nConsider the following conversation history:\n" + history_str

        return await self.query(message, top_k=top_k, system_prompt=system)
