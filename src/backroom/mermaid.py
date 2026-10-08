"""Parser for the Mermaid *flowchart* subset used by backroom.

Supported:
  flowchart TD|TB|BT|LR|RL   (or `graph ...`)
  nodes      id, id["label"], id(...), id([...]), id[(...)], id[[...]], id((...)),
             id{...}, id{{...}}, id[/.../], id>...]          (+ optional :::class)
  edges      -->  ---  -.->  -.-  ==>  ===  <-->  --o  --x   chains A --> B --> C
             labels: A -->|text| B   or   A -- text --> B
             fan-out: A & B --> C & D
  subgraph   subgraph id["Title"] ... end   (nested), `direction LR` inside
  classes    class a,b role   /   classDef role fill:#..,stroke:#..,color:#..
Ignored:     style, linkStyle, click, %% comments
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


class MermaidError(ValueError):
    def __init__(self, msg: str, line_no: int | None = None, line: str | None = None):
        self.line_no, self.line = line_no, line
        where = f" (line {line_no}: {line.strip()!r})" if line_no else ""
        super().__init__(msg + where)


@dataclass
class Node:
    id: str
    label: str
    shape: str = "rect"
    cls: str | None = None
    group: str | None = None
    explicit: bool = False  # declared with a shape/label at least once


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    style: str = "solid"      # solid | dotted | thick
    arrow_end: bool = True
    arrow_start: bool = False


@dataclass
class Group:
    id: str
    title: str
    parent: str | None = None
    direction: str | None = None
    cls: str | None = None


@dataclass
class Graph:
    direction: str = "TB"
    nodes: dict = field(default_factory=dict)       # id -> Node (insertion ordered)
    edges: list = field(default_factory=list)
    groups: dict = field(default_factory=dict)      # id -> Group
    class_defs: dict = field(default_factory=dict)  # name -> {fill, stroke, color, dashed}

    def items_in(self, gid):
        """Direct children (nodes, groups) of group gid (None = root)."""
        nodes = [n.id for n in self.nodes.values() if n.group == gid]
        groups = [g.id for g in self.groups.values() if g.parent == gid]
        return nodes, groups


# ---------------------------------------------------------------- lexing ----
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# opener -> (closer, shape)   longest openers first
_SHAPES = [
    ("([", "])", "stadium"),
    ("[(", ")]", "cylinder"),
    ("[[", "]]", "subroutine"),
    ("((", "))", "circle"),
    ("{{", "}}", "hexagon"),
    ("[/", "/]", "parallelogram"),
    ("[\\", "\\]", "parallelogram"),
    ("[", "]", "rect"),
    ("(", ")", "round"),
    ("{", "}", "diamond"),
    (">", "]", "flag"),
]
_LINK_TEXT = re.compile(
    r"\s*(<?)(--|==|-\.)\s*([^\s\-=.>|][^|]*?)\s*(-{2,}>|={2,}>|\.+->|-{3,}|={3,}|\.+-)\s*")
_LINK = re.compile(
    r"\s*(<?)(-{2,}>|={2,}>|-\.+->|-{3,}|={3,}|-\.+-|--o|--x|==o|==x)\s*(?:\|([^|]*)\|)?\s*")
_DIR = {"TD": "TB", "TB": "TB", "BT": "BT", "LR": "LR", "RL": "RL"}


def clean_label(text: str) -> str:
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] == '"':
        t = t[1:-1]
    if len(t) >= 2 and t[0] == t[-1] == "`":
        t = t[1:-1]
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.IGNORECASE)
    t = t.replace("#quot;", '"').replace("#amp;", "&").replace("#lt;", "<").replace("#gt;", ">")
    t = re.sub(r"</?(b|i|strong|em|small)>", "", t, flags=re.IGNORECASE)
    return t.strip()


def _link_kind(tok: str):
    style = "dotted" if "." in tok else ("thick" if "=" in tok else "solid")
    arrow = tok.endswith(">")
    return style, arrow


class _Parser:
    def __init__(self, text: str):
        self.g = Graph()
        self.stack: list[str] = []
        self.text = text
        self.ln = 0
        self.line = ""

    def err(self, msg):
        raise MermaidError(msg, self.ln, self.line)

    # -- node reference --------------------------------------------------
    def node_ref(self, s: str, i: int):
        m = _ID.match(s, i)
        if not m:
            self.err(f"expected a node id at column {i + 1}")
        nid, i = m.group(0), m.end()
        label = shape = None
        for op, cl, shp in _SHAPES:
            if s.startswith(op, i):
                j = i + len(op)
                k = j
                while k < len(s) and s[k] == " ":
                    k += 1
                if k < len(s) and s[k] == '"':
                    end_q = s.find('"', k + 1)
                    if end_q < 0:
                        self.err("unclosed quote in node label")
                    close = s.find(cl, end_q + 1)
                    if close < 0:
                        self.err(f"node {nid} is missing closing '{cl}'")
                    raw = s[k:end_q + 1]
                else:
                    close = s.find(cl, j)
                    if close < 0:
                        self.err(f"node {nid} is missing closing '{cl}'")
                    raw = s[j:close]
                label, shape, i = clean_label(raw), shp, close + len(cl)
                break
        cls = None
        if s.startswith(":::", i):
            m2 = _ID.match(s, i + 3)
            if not m2:
                self.err("expected class name after :::")
            cls, i = m2.group(0), m2.end()
        self.declare(nid, label, shape, cls)
        return nid, i

    def declare(self, nid, label, shape, cls):
        g = self.g
        cur = self.stack[-1] if self.stack else None
        if nid in g.groups and label is None:
            if cls:
                g.groups[nid].cls = cls
            return
        n = g.nodes.get(nid)
        if n is None:
            n = g.nodes[nid] = Node(nid, label if label is not None else nid, shape or "rect", group=cur)
        if label is not None:
            n.label, n.shape, n.explicit = label, shape, True
            n.group = cur if (cur is not None or n.group is None) else n.group
        if cls:
            n.cls = cls

    def node_list(self, s, i):
        ids = []
        while True:
            while i < len(s) and s[i] == " ":
                i += 1
            nid, i = self.node_ref(s, i)
            ids.append(nid)
            j = i
            while j < len(s) and s[j] == " ":
                j += 1
            if j < len(s) and s[j] == "&":
                i = j + 1
                continue
            return ids, i

    # -- statements ------------------------------------------------------
    def statement(self, s):
        left, i = self.node_list(s, 0)
        while i < len(s):
            rest = s[i:]
            if not rest.strip():
                break
            m = _LINK_TEXT.match(s, i)
            if m:
                bidir, tok, lab = m.group(1), m.group(4), m.group(3)
            else:
                m = _LINK.match(s, i)
                if not m:
                    self.err(f"could not understand text near {rest.strip()[:25]!r}")
                bidir, tok, lab = m.group(1), m.group(2), m.group(3) or ""
            style, arrow = _link_kind(tok)
            i = m.end()
            right, i = self.node_list(s, i)
            for a in left:
                for b in right:
                    self.g.edges.append(Edge(a, b, clean_label(lab) if lab else "", style,
                                             arrow, bool(bidir)))
            left = right

    def parse(self) -> Graph:
        g = self.g
        header_seen = False
        lines = self.text.replace("\r\n", "\n").split("\n")
        for self.ln, raw in enumerate(lines, 1):
            self.line = raw
            s = raw.split("%%", 1)[0].strip().rstrip(";").strip()
            if not s:
                continue
            if not header_seen:
                m = re.match(r"(flowchart|graph)\s*([A-Z]{2})?\s*$", s)
                if not m:
                    self.err("diagram must start with 'flowchart TD' or 'flowchart LR'")
                g.direction = _DIR.get(m.group(2) or "TB", "TB")
                header_seen = True
                continue
            low = s.lower()
            if low.startswith("subgraph"):
                body = s[8:].strip()
                m = re.match(r'([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(.*?)\s*\]\s*$', body)
                if m:
                    gid, title = m.group(1), clean_label(m.group(2))
                elif _ID.fullmatch(body):
                    gid, title = body, body
                else:
                    title = clean_label(body)
                    gid = re.sub(r"\W+", "_", title).strip("_") or f"group{len(g.groups) + 1}"
                if gid in g.groups:
                    self.err(f"subgraph id '{gid}' used twice")
                if gid in g.nodes and g.nodes[gid].explicit:
                    self.err(f"'{gid}' is already a node; give the subgraph a different id")
                g.nodes.pop(gid, None)
                g.groups[gid] = Group(gid, title, self.stack[-1] if self.stack else None)
                self.stack.append(gid)
                continue
            if low == "end":
                if not self.stack:
                    self.err("'end' without a matching 'subgraph'")
                self.stack.pop()
                continue
            if low.startswith("direction "):
                d = s.split()[1].upper()
                if self.stack:
                    g.groups[self.stack[-1]].direction = _DIR.get(d, None)
                continue
            if low.startswith("classdef "):
                parts = s.split(None, 2)
                if len(parts) == 3:
                    props = {}
                    for kv in parts[2].split(","):
                        if ":" in kv:
                            k, v = kv.split(":", 1)
                            props[k.strip()] = v.strip()
                    for name in parts[1].split(","):
                        g.class_defs[name] = {
                            "fill": props.get("fill"), "stroke": props.get("stroke"),
                            "font": props.get("color"),
                            "dashed": "stroke-dasharray" in props}
                continue
            if low.startswith("class "):
                parts = s.split()
                if len(parts) < 3:
                    self.err("class statement needs ids and a class name")
                cls = parts[-1]
                for nid in "".join(parts[1:-1]).split(","):
                    nid = nid.strip()
                    if not nid:
                        continue
                    if nid in g.groups:
                        g.groups[nid].cls = cls
                    elif nid in g.nodes:
                        g.nodes[nid].cls = cls
                    else:
                        self.err(f"class refers to unknown id '{nid}'")
                continue
            if low.startswith(("style ", "linkstyle ", "click ", "accTitle", "accDescr")):
                continue
            self.statement(s)
        if not header_seen:
            raise MermaidError("empty diagram")
        if self.stack:
            raise MermaidError(f"subgraph '{self.stack[-1]}' is missing its 'end'")
        # implicit nodes whose id turned out to be a group -> edges target the group
        for gid in list(g.groups):
            n = g.nodes.get(gid)
            if n and not n.explicit:
                del g.nodes[gid]
        for e in g.edges:
            for end in (e.src, e.dst):
                if end not in g.nodes and end not in g.groups:
                    raise MermaidError(f"edge refers to unknown id '{end}'")
        if not g.nodes:
            raise MermaidError("diagram has no nodes")
        return g


def parse(text: str) -> Graph:
    return _Parser(text).parse()


def extract_mermaid(reply: str) -> str:
    """Pull the Mermaid code out of a model reply."""
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL)
    m = re.search(r"```(?:mermaid)?\s*\n(.*?)```", reply, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"((?:flowchart|graph)\s+[A-Z]{2}.*)", reply, flags=re.DOTALL)
    return m.group(1).strip() if m else reply.strip()
