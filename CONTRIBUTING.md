# Contributing to Backroom

Thanks for helping! This project exists for people who need AI help but can't send their data to the cloud, so **privacy is the first review criterion**. No change may send data off the machine by default.

## Setup

```bash
git clone https://github.com/<you>/backroom && cd backroom
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

The tests don't need Ollama or LM Studio, because `tests/conftest.py` runs a fake OpenAI-compatible server. Please keep it that way, so CI stays fast and offline.

## Where things live

| Module | Responsibility |
|---|---|
| `mermaid.py` | Parse the supported Mermaid flowchart subset into a `Graph`; clear, line-numbered errors (these are fed back to the model) |
| `layout.py` | Compound layered layout: positions relative to the parent container |
| `drawio.py` | `Graph` + layout → draw.io XML, plus the SVG preview |
| `style.py` | PowerPoint theme → `style.json` roles |
| `rag.py` | Document readers, chunking, local vector index |
| `llm.py` | OpenAI-compatible client, localhost-only guard |
| `prompts.py` | All model instructions as plain text |
| `cli.py` | The `br` command |

## Guidelines

- **Add a test with every change.** Parser changes need a case in `tests/test_mermaid.py`, including the error message for invalid input.
- **Error messages are for two readers:** a person and a small local model. Say what is wrong and where, in one line.
- **Keep dependencies light.** Anything heavy, such as Graphviz or a web UI, should be an optional extra (`pip install backroom[web]`).
- **Never commit real company documents, templates or generated outputs.** Use invented examples like `examples/web_app.mmd`.
- **Prompt changes:** describe in the PR which model and size you tested with, and include a before/after `.mmd`.

## Reporting issues

Please include:
- Your OS, `br --version`, the backend (Ollama or LM Studio) and the model name.
- The failing `.mmd` file or prompt. Remove anything confidential first.
