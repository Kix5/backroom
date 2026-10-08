"""Minimal client for a *local* OpenAI-compatible server (Ollama or LM Studio).

Both expose the same API:
  Ollama     http://localhost:11434/v1
  LM Studio  http://localhost:1234/v1
Requests to non-local hosts are refused unless allow_remote_endpoints is true,
so confidential text can't be sent off the machine by a config mistake.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class LLMError(RuntimeError):
    pass


def strip_think(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    return text.split("</think>", 1)[-1].strip()


class LLM:
    def __init__(self, cfg: dict, backend: str | None = None):
        name = backend or cfg["backend"]
        if name not in cfg["backends"]:
            raise LLMError(f"unknown backend '{name}' (choose: {', '.join(cfg['backends'])})")
        b = cfg["backends"][name]
        self.name = name
        self.base = b["base_url"].rstrip("/")
        self.chat_model = b["chat_model"]
        self.embed_model = b["embed_model"]
        self.timeout = cfg.get("timeout_s", 600)
        self.temperature = cfg.get("temperature", 0.2)
        host = urlparse(self.base).hostname or ""
        if host not in LOCAL_HOSTS and not cfg.get("allow_remote_endpoints", False):
            raise LLMError(f"refusing to send data to non-local host '{host}'. "
                           "Set allow_remote_endpoints=true in config.json only if that "
                           "server is inside your own network.")

    def _post(self, path: str, payload: dict) -> dict:
        try:
            r = requests.post(f"{self.base}{path}", json=payload, timeout=self.timeout)
        except requests.ConnectionError:
            hint = ("start Ollama (it runs in the system tray) or run `ollama serve`"
                    if self.name == "ollama" else
                    "open LM Studio > Developer tab > Start Server, and load the models")
            raise LLMError(f"cannot reach {self.name} at {self.base} - {hint}.") from None
        if r.status_code >= 400:
            msg = r.text[:300]
            if "not found" in msg.lower() or r.status_code == 404:
                pull = (f"run `ollama pull {payload.get('model')}`" if self.name == "ollama"
                        else "download and load it in LM Studio")
                msg += f"\n-> model '{payload.get('model')}' is not available: {pull}"
            raise LLMError(f"{self.name} returned HTTP {r.status_code}: {msg}")
        return r.json()

    def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        data = self._post("/chat/completions", {
            "model": self.chat_model, "messages": messages, "stream": False,
            "temperature": self.temperature if temperature is None else temperature})
        return strip_think(data["choices"][0]["message"].get("content") or "")

    def embed(self, texts: list[str], batch: int = 32) -> list[list[float]]:
        out = []
        for i in range(0, len(texts), batch):
            data = self._post("/embeddings", {"model": self.embed_model,
                                              "input": texts[i:i + batch]})
            out.extend(d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"]))
        return out
