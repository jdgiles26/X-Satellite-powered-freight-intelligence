"""
ARGUS AI — Ollama Async LLM Client
"""

import os
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("ARGUS.AI.LLM")

DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_GENERATE_MODEL = os.getenv("OLLAMA_GENERATE_MODEL", "llama3")
DEFAULT_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")


class OllamaClient:
    """Async HTTP client for Ollama with graceful degradation."""

    def __init__(self, base_url: str = DEFAULT_HOST):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
        self._healthy: Optional[bool] = None

    async def healthcheck(self) -> bool:
        """Probe Ollama root endpoint to verify availability."""
        try:
            resp = await self.client.get(f"{self.base_url}/", timeout=5.0)
            self._healthy = resp.status_code < 500
        except Exception as exc:
            logger.warning(f"Ollama healthcheck failed: {exc}")
            self._healthy = False
        return self._healthy

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Call /api/generate with stream=False and return the parsed JSON.
        Falls back to a synthetic error response if Ollama is unreachable.
        """
        payload: Dict[str, Any] = {
            "model": model or DEFAULT_GENERATE_MODEL,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options

        try:
            resp = await self.client.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.debug(f"Ollama generate OK (model={payload['model']})")
            return data
        except httpx.HTTPStatusError as exc:
            logger.error(f"Ollama generate HTTP error: {exc.response.status_code} — {exc.response.text}")
            return {
                "response": "",
                "error": f"Ollama HTTP {exc.response.status_code}",
                "done": True,
            }
        except httpx.RequestError as exc:
            logger.warning(f"Ollama generate request error: {exc}")
            return {
                "response": "",
                "error": f"Ollama unreachable: {exc}",
                "done": True,
            }
        except Exception as exc:
            logger.error(f"Ollama generate unexpected error: {exc}")
            return {
                "response": "",
                "error": f"Unexpected error: {exc}",
                "done": True,
            }

    async def embed(
        self,
        text: str,
        model: Optional[str] = None,
    ) -> List[float]:
        """
        Call /api/embed and return the embedding vector.
        Falls back to a zero-vector of length 768 if Ollama is unreachable.
        """
        payload = {
            "model": model or DEFAULT_EMBED_MODEL,
            "input": text,
        }
        try:
            resp = await self.client.post(
                f"{self.base_url}/api/embed",
                json=payload,
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings")
            if embeddings and isinstance(embeddings, list) and len(embeddings) > 0:
                vector = embeddings[0]
                if isinstance(vector, list):
                    return vector
            # Some Ollama versions return single embedding directly
            if isinstance(embeddings, list) and len(embeddings) > 0 and isinstance(embeddings[0], float):
                return embeddings
            logger.warning(f"Ollama embed unexpected shape: {data.keys()}")
            return [0.0] * 768
        except httpx.HTTPStatusError as exc:
            logger.error(f"Ollama embed HTTP error: {exc.response.status_code}")
            return [0.0] * 768
        except httpx.RequestError as exc:
            logger.warning(f"Ollama embed request error: {exc}")
            return [0.0] * 768
        except Exception as exc:
            logger.error(f"Ollama embed unexpected error: {exc}")
            return [0.0] * 768

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
