"""Configuration: built-in defaults, overridden by backroom.json in the working folder."""
from __future__ import annotations

import copy
import json
from pathlib import Path

CONFIG_NAME = "backroom.json"

DEFAULT_CONFIG: dict = {
    "backend": "ollama",
    "backends": {
        "ollama": {
            "base_url": "http://localhost:11434/v1",
            "chat_model": "qwen3:14b",
            "embed_model": "nomic-embed-text",
        },
        "lmstudio": {
            "base_url": "http://localhost:1234/v1",
            "chat_model": "qwen/qwen3-14b",
            "embed_model": "text-embedding-nomic-embed-text-v1.5",
        },
    },
    "allow_remote_endpoints": False,
    "temperature": 0.2,
    "timeout_s": 900,
    "rag": {
        "top_k": 6,
        "chunk_chars": 1200,
        "overlap_chars": 200,
        "max_context_chars": 8000,
        "doc_prefix": "search_document: ",
        "query_prefix": "search_query: ",
    },
    "index_dir": ".backroom/index",
    "output_dir": "output",
    "notes_dir": "notes",
    "style_file": "style.json",
    "drawio_exe": "",
}

PATH_KEYS = ("index_dir", "output_dir", "notes_dir", "style_file")


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None, workdir: str | Path | None = None) -> dict:
    """Load config. Relative paths in the config resolve against the config file's folder."""
    workdir = Path(workdir or Path.cwd())
    cfg_path = Path(path) if path else workdir / CONFIG_NAME
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    base = workdir
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            cfg = _merge(cfg, json.load(f))
        base = cfg_path.resolve().parent
    elif path:
        raise FileNotFoundError(f"config file not found: {cfg_path}")
    for key in PATH_KEYS:
        p = Path(cfg[key])
        cfg[key] = str(p if p.is_absolute() else base / p)
    cfg["_config_path"] = str(cfg_path) if cfg_path.exists() else None
    return cfg


def write_default_config(folder: str | Path) -> Path:
    target = Path(folder) / CONFIG_NAME
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    target.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
    return target
