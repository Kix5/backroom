"""Command-line interface: the `br` command.

  br init                                  create backroom.json in this folder
  br check                                 test the connection to Ollama / LM Studio
  br style   <template.potx|.pptx>         build style.json from a PowerPoint template
  br ingest  <folder or files...>          add documents to the private search index
  br draw    "describe the diagram"        generate Mermaid -> .drawio (+ preview)
  br draw    "change ..." --revise x.mmd   revise an existing diagram
  br convert <file.mmd>                    convert hand-written Mermaid to .drawio
  br ask     "question"                    answer from your documents, with sources
  br notes   <raw_notes.txt>               clean up notes into structured Markdown

To use the other backend for one run, put it before the command:
  br --backend lmstudio draw "..."
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from . import __version__, drawio, mermaid, prompts
from .config import load_config, write_default_config
from .llm import LLM, LLMError

MAX_FIX_ATTEMPTS = 3


# ----------------------------------------------------------------- helpers --
def fill(template: str, **values) -> str:
    for k, v in values.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def slugify(text: str, n: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    return (s[:n].rstrip("-") or "diagram")


def load_style(cfg) -> dict:
    p = Path(cfg["style_file"])
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    print("  (no style.json yet - using default colours; run `br style <template>`)")
    return {}


def get_index(cfg, llm):
    from .rag import Index
    return Index(cfg["index_dir"], llm, cfg.get("rag", {}))


def retrieve(cfg, llm, query: str, use_rag: bool, style_hint: bool = False) -> tuple[str, list]:
    if not use_rag:
        return "(none)", []
    from .rag import format_context
    idx = get_index(cfg, llm)
    if not idx.chunks:
        return "(no documents indexed yet)", []
    hits = idx.search(query)
    if style_hint:  # always pull the most relevant bits of the style guide too
        style_name = Path(load_style(cfg).get("source", "")).name
        if style_name:
            names = {h["source"] + h["loc"] for h in hits}
            for h in idx.search("diagram style colours shapes rules " + query, k=3, only=style_name):
                if h["source"] + h["loc"] not in names:
                    hits.append(h)
    return format_context(hits, cfg.get("rag", {}).get("max_context_chars", 8000)), hits


def print_sources(hits):
    if hits:
        print("\nSources used:")
        seen = set()
        for i, h in enumerate(hits, 1):
            key = (h["name"], h["loc"])
            if key in seen:
                continue
            seen.add(key)
            print(f"  [{i}] {h['name']}" + (f" ({h['loc']})" if h["loc"] else ""))


def find_drawio(cfg) -> str | None:
    if cfg.get("drawio_exe") and Path(cfg["drawio_exe"]).exists():
        return cfg["drawio_exe"]
    candidates = []
    if platform.system() == "Windows":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("LOCALAPPDATA", "") + r"\Programs"):
            candidates.append(Path(base) / "draw.io" / "draw.io.exe")
    elif platform.system() == "Darwin":
        candidates.append(Path("/Applications/draw.io.app/Contents/MacOS/draw.io"))
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("drawio") or shutil.which("draw.io")


def open_file(path: Path):
    if platform.system() == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def write_outputs(cfg, code: str, graph, name: str, export: str | None, do_open: bool):
    out = Path(cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    style = load_style(cfg)
    xml, boxes = drawio.to_drawio(graph, style, page_name=name)
    mmd_p, dio_p, svg_p = out / f"{name}.mmd", out / f"{name}.drawio", out / f"{name}.preview.svg"
    mmd_p.write_text(code + "\n", encoding="utf-8")
    dio_p.write_text(xml, encoding="utf-8")
    svg_p.write_text(drawio.to_svg(graph, boxes, style), encoding="utf-8")
    print(f"\nSaved:\n  {mmd_p}\n  {dio_p}   <- open in draw.io to adjust\n  {svg_p}   <- quick preview")
    if export:
        exe = find_drawio(cfg)
        if not exe:
            print("  ! draw.io desktop not found - install it or set drawio_exe in backroom.json")
        else:
            target = out / f"{name}.{export}"
            r = subprocess.run([exe, "-x", "-f", export, "-o", str(target), str(dio_p)],
                               capture_output=True, text=True)
            print(f"  {target}" if r.returncode == 0 else f"  ! export failed: {r.stderr[:200]}")
    if do_open:
        open_file(dio_p)


def role_text(style: dict) -> str:
    roles = style.get("roles") or {"primary": {"description": "main components"}}
    return "\n".join(f"    {k}: {v.get('description', '')}" for k, v in roles.items())


# ---------------------------------------------------------------- commands --
def cmd_init(cfg, a):
    target = write_default_config(Path.cwd())
    print(f"Created {target}. Edit the model names to match what you installed, then run `br check`.")


def cmd_check(cfg, a):
    llm = LLM(cfg, a.backend)
    print(f"Backend: {llm.name} at {llm.base}")
    print(f"  chat model:  {llm.chat_model} ...", end=" ", flush=True)
    print("OK -", llm.chat([{"role": "user", "content": "Reply with the single word: ready"}])[:40])
    print(f"  embed model: {llm.embed_model} ...", end=" ", flush=True)
    print(f"OK - {len(llm.embed(['test'])[0])} dimensions")


def cmd_style(cfg, a):
    from .style import save_style
    st = save_style(a.template, cfg["style_file"])
    print(f"Wrote {cfg['style_file']}")
    print(f"  theme: {st['theme_name']}   font: {st['font']}")
    for r, v in st["roles"].items():
        print(f"  {r:9s} fill {v['fill']}  border {v['stroke']}  - {v['description']}")
    print("\nEdit style.json to rename roles, change descriptions, or add rules the model must follow.")
    print("Tip: also run `br ingest <template>` so written style rules in the slides are searchable.")


def cmd_ingest(cfg, a):
    llm = LLM(cfg, a.backend)
    if a.rebuild and Path(cfg["index_dir"]).exists():
        shutil.rmtree(cfg["index_dir"])
    idx = get_index(cfg, llm)
    print(f"Indexing with {llm.name} / {llm.embed_model} ...")
    added, skipped = idx.add_paths(a.paths)
    print(f"Done: {added} file(s) indexed, {skipped} unchanged, {len(idx.chunks)} chunks total.")


def generate(cfg, llm, messages) -> tuple[str, object]:
    last_err = None
    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        print(f"  asking {llm.chat_model} (attempt {attempt}) ...", flush=True)
        reply = llm.chat(messages)
        code = mermaid.extract_mermaid(reply)
        try:
            return code, mermaid.parse(code)
        except mermaid.MermaidError as e:
            last_err = e
            print(f"  ! invalid Mermaid: {e}")
            messages = messages + [{"role": "assistant", "content": reply},
                                   {"role": "user", "content": fill(prompts.FIX_USER, error=str(e))}]
    raise SystemExit(f"Model could not produce valid Mermaid after {MAX_FIX_ATTEMPTS} tries: {last_err}\n"
                     "Try a larger model, a simpler request, or fix the .mmd and run `br convert`.")


def cmd_draw(cfg, a):
    llm = LLM(cfg, a.backend)
    style = load_style(cfg)
    system = fill(prompts.DIAGRAM_SYSTEM, roles=role_text(style),
                  rules="\n".join(f"- {r}" for r in style.get("rules", [])) or "- (none)")
    context, hits = retrieve(cfg, llm, a.request, not a.no_rag, style_hint=True)
    if a.revise:
        current = Path(a.revise).read_text(encoding="utf-8")
        user = fill(prompts.REVISE_USER, current=current, request=a.request, context=context)
        name = a.name or Path(a.revise).stem
    else:
        user = fill(prompts.DIAGRAM_USER, context=context, request=a.request)
        name = a.name or f"{slugify(a.request)}-{dt.datetime.now():%Y%m%d-%H%M}"
    code, graph = generate(cfg, llm, [{"role": "system", "content": system},
                                       {"role": "user", "content": user}])
    unknown = sorted({n.cls for n in graph.nodes.values() if n.cls and n.cls not in style.get("roles", {})})
    if style and unknown:
        print(f"  note: unknown style classes {unknown} - drawn with the default role")
    print(f"  diagram: {len(graph.nodes)} nodes, {len(graph.edges)} links, {len(graph.groups)} groups")
    write_outputs(cfg, code, graph, name, a.export, a.open)
    print_sources(hits)


def cmd_convert(cfg, a):
    code = Path(a.file).read_text(encoding="utf-8")
    code = mermaid.extract_mermaid(code)
    try:
        graph = mermaid.parse(code)
    except mermaid.MermaidError as e:
        raise SystemExit(f"Cannot convert: {e}") from None
    write_outputs(cfg, code, graph, a.name or Path(a.file).stem, a.export, a.open)


def cmd_ask(cfg, a):
    llm = LLM(cfg, a.backend)
    context, hits = retrieve(cfg, llm, a.question, True)
    if not hits:
        raise SystemExit("No documents indexed yet - run `br ingest <folder>` first.")
    print(llm.chat([{"role": "system", "content": prompts.ASK_SYSTEM},
                    {"role": "user", "content": fill(prompts.ASK_USER, context=context, question=a.question)}]))
    print_sources(hits)


def cmd_notes(cfg, a):
    llm = LLM(cfg, a.backend)
    raw = Path(a.file).read_text(encoding="utf-8", errors="ignore")
    context, _ = retrieve(cfg, llm, raw[:1500], not a.no_rag)
    md = llm.chat([{"role": "system", "content": prompts.NOTES_SYSTEM},
                   {"role": "user", "content": fill(prompts.NOTES_USER, context=context, notes=raw)}])
    out = Path(cfg["notes_dir"])
    out.mkdir(parents=True, exist_ok=True)
    m = re.search(r"^#\s+(.+)$", md, flags=re.MULTILINE)
    title = slugify(m.group(1) if m else Path(a.file).stem, 60)
    target = out / f"{dt.date.today():%Y-%m-%d} {title}.md"
    target.write_text(md + "\n", encoding="utf-8")
    print(md)
    print(f"\nSaved: {target}")


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(prog="br", description="Backroom: a private, local AI workspace",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--version", action="version", version=f"backroom {__version__}")
    ap.add_argument("--backend", choices=["ollama", "lmstudio"], help="override the configured backend")
    ap.add_argument("--config", metavar="FILE", help="config file (default: ./backroom.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create backroom.json in the current folder")
    sub.add_parser("check", help="test the connection to the local model")
    p = sub.add_parser("style", help="build style.json from a PowerPoint template")
    p.add_argument("template")
    p = sub.add_parser("ingest", help="index documents for RAG")
    p.add_argument("paths", nargs="+")
    p.add_argument("--rebuild", action="store_true", help="delete the index and start again")
    for name in ("draw", "convert"):
        p = sub.add_parser(name)
        if name == "draw":
            p.add_argument("request")
            p.add_argument("--revise", metavar="FILE.mmd", help="change an existing diagram")
            p.add_argument("--no-rag", action="store_true", help="don't use indexed documents")
        else:
            p.add_argument("file")
        p.add_argument("--name", help="output file name (without extension)")
        p.add_argument("--export", choices=["svg", "png", "pdf"], help="also export via draw.io desktop")
        p.add_argument("--open", action="store_true", help="open the .drawio file when done")
    p = sub.add_parser("ask", help="ask a question about your documents")
    p.add_argument("question")
    p = sub.add_parser("notes", help="structure raw notes into Markdown")
    p.add_argument("file")
    p.add_argument("--no-rag", action="store_true")

    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise SystemExit(f"Config error: {e}") from None
    try:
        {"init": cmd_init, "check": cmd_check, "style": cmd_style, "ingest": cmd_ingest, "draw": cmd_draw,
         "convert": cmd_convert, "ask": cmd_ask, "notes": cmd_notes}[a.cmd](cfg, a)
    except (LLMError, FileExistsError) as e:
        raise SystemExit(f"Error: {e}") from None


if __name__ == "__main__":
    main()
