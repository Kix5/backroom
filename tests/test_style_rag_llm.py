import json
import shutil

import pytest

from backroom.config import load_config
from backroom.llm import LLM, LLMError, strip_think
from backroom.rag import Index, chunk, read_file
from backroom.style import build_style, read_theme


def test_theme_colours_and_fonts_from_pptx(template):
    th = read_theme(str(template))
    assert th["colours"]["accent1"].startswith("#") and len(th["colours"]) >= 10
    assert th["fonts"]["minorFont"]


def test_potx_template_is_supported(template, tmp_path):
    potx = tmp_path / "t.potx"
    shutil.copy(template, potx)
    style = build_style(str(potx))
    assert {"primary", "network", "security", "data", "edge", "app", "phase2"} <= set(style["roles"])
    assert style["roles"]["phase2"]["dashed"] is True
    sections = read_file(potx)  # text of slides is readable for RAG
    assert "hexagon" in sections[0][1]


def test_chunking_respects_size_and_overlap():
    text = ". ".join(f"Sentence number {i} about the system" for i in range(200))
    parts = chunk(text, 400, 80)
    assert len(parts) > 5 and all(len(p) <= 400 for p in parts)
    assert chunk("short", 400, 80) == ["short"] and chunk("   ", 400, 80) == []


def test_index_add_search_and_incremental(tmp_path, fake_server):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "network.md").write_text("The firewall pair protects the database tier.", encoding="utf-8")
    (docs / "people.txt").write_text("Alice owns the onboarding checklist.", encoding="utf-8")
    cfg = load_config(workdir=tmp_path)
    cfg["backends"]["ollama"].update(base_url=fake_server.url)
    llm = LLM(cfg)
    idx = Index(str(tmp_path / "idx"), llm, cfg["rag"])
    assert idx.add_paths([str(docs)], log=lambda *_: None) == (2, 0)
    assert Index(str(tmp_path / "idx"), llm, cfg["rag"]).add_paths([str(docs)], log=lambda *_: None) == (0, 2)
    hits = idx.search("which firewall protects the database", k=1)
    assert hits[0]["name"] == "network.md"
    sent = [r["body"]["input"] for r in fake_server.requests if r["path"].endswith("/embeddings")]
    assert sent[0][0].startswith("search_document: ") and sent[-1][0].startswith("search_query: ")


def test_remote_endpoints_are_refused():
    cfg = {"backend": "x", "backends": {"x": {"base_url": "https://api.example.com/v1",
                                              "chat_model": "m", "embed_model": "e"}}}
    with pytest.raises(LLMError, match="non-local"):
        LLM(cfg)
    cfg["allow_remote_endpoints"] = True
    LLM(cfg)  # explicitly allowed


def test_friendly_error_when_server_is_down():
    cfg = {"backend": "ollama", "backends": {"ollama": {"base_url": "http://127.0.0.1:9/v1",
                                                        "chat_model": "m", "embed_model": "e"}}}
    with pytest.raises(LLMError, match="cannot reach ollama"):
        LLM(cfg).chat([{"role": "user", "content": "hi"}])


def test_strip_think():
    assert strip_think("<think>a\nb</think>answer") == "answer"
    assert strip_think("reasoning</think> answer") == "answer"


def test_config_defaults_and_overrides(tmp_path):
    cfg = load_config(workdir=tmp_path)
    assert cfg["backend"] == "ollama" and cfg["_config_path"] is None
    (tmp_path / "backroom.json").write_text(json.dumps({"backend": "lmstudio", "rag": {"top_k": 2}}))
    cfg = load_config(workdir=tmp_path)
    assert cfg["backend"] == "lmstudio" and cfg["rag"]["top_k"] == 2
    assert cfg["rag"]["chunk_chars"] == 1200  # nested defaults kept
    assert cfg["output_dir"].startswith(str(tmp_path))
