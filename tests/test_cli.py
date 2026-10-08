import json
import shutil
from pathlib import Path

import pytest

from backroom.cli import main
from tests.conftest import BROKEN_DIAGRAM, GOOD_DIAGRAM

EXAMPLE = Path(__file__).parent.parent / "examples" / "web_app.mmd"


def test_init_creates_config_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["init"])
    assert json.loads((tmp_path / "backroom.json").read_text())["backend"] == "ollama"
    with pytest.raises(SystemExit):
        main(["init"])


def test_convert_writes_three_outputs(workdir):
    shutil.copy(EXAMPLE, workdir / "web.mmd")
    main(["convert", "web.mmd"])
    for ext in (".mmd", ".drawio", ".preview.svg"):
        assert (workdir / "output" / f"web{ext}").exists()


def test_check(workdir, capsys):
    main(["check"])
    assert "dimensions" in capsys.readouterr().out


def test_style_ingest_draw_end_to_end(workdir, template, fake_server, capsys):
    main(["style", str(template)])
    assert json.loads((workdir / "style.json").read_text())["roles"]
    docs = workdir / "docs"
    docs.mkdir()
    (docs / "arch.md").write_text("The API talks to a PostgreSQL database.", encoding="utf-8")
    main(["ingest", str(docs), str(template)])
    main(["draw", "web app with API and database", "--name", "arch"])
    out = capsys.readouterr().out
    assert (workdir / "output" / "arch.drawio").exists()
    assert "Sources used" in out
    chat = fake_server.chats()[-1]["body"]["messages"]
    assert "PostgreSQL" in chat[1]["content"]          # RAG context reached the model
    assert 'id{{"Name"}}' in chat[0]["content"]         # prompt braces not mangled
    assert "edge:" in chat[0]["content"]                # style roles listed


def test_draw_retries_after_invalid_mermaid(workdir, fake_server, capsys):
    fake_server.diagram_replies = [BROKEN_DIAGRAM, GOOD_DIAGRAM]
    main(["draw", "anything", "--no-rag", "--name", "retry"])
    assert "invalid Mermaid" in capsys.readouterr().out
    assert (workdir / "output" / "retry.drawio").exists()
    fix_turn = fake_server.chats()[-1]["body"]["messages"][-1]["content"]
    assert "could not be parsed" in fix_turn


def test_draw_gives_up_after_repeated_failures(workdir, fake_server):
    fake_server.diagram_replies = [BROKEN_DIAGRAM]
    with pytest.raises(SystemExit, match="could not produce valid Mermaid"):
        main(["draw", "anything", "--no-rag"])


def test_revise_keeps_name(workdir, fake_server):
    (workdir / "old.mmd").write_text("flowchart LR\n a --> b\n", encoding="utf-8")
    main(["draw", "add a database", "--revise", "old.mmd", "--no-rag"])
    assert (workdir / "output" / "old.drawio").exists()
    assert "a --> b" in fake_server.chats()[-1]["body"]["messages"][1]["content"]


def test_ask_and_notes(workdir, fake_server, capsys):
    docs = workdir / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("Backups run nightly at 02:00.", encoding="utf-8")
    main(["ingest", str(docs)])
    main(["ask", "when do backups run?"])
    assert "Answer from documents" in capsys.readouterr().out
    fake_server.text_reply = "# Weekly sync\n## Summary\n- Backups agreed"
    (workdir / "raw.txt").write_text("sync: agreed backups", encoding="utf-8")
    main(["notes", "raw.txt"])
    assert list((workdir / "notes").glob("*weekly-sync.md"))
