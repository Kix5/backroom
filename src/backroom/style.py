"""Build an editable style.json from a company PowerPoint template (.pptx / .potx).

Reads the theme colour scheme (dk1, lt1, dk2, lt2, accent1-6) and theme fonts
directly from the file's XML, then maps them to diagram *roles*. Edit the
generated style.json by hand to rename roles, change which accent each role
uses, or add written style rules that the model must follow.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
SLOTS = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4",
         "accent5", "accent6", "hlink", "folHlink"]

# role -> (theme slot, description given to the model)
ROLE_MAP = [
    ("primary",  "accent1", "core platform services and the main system components"),
    ("network",  "accent2", "network devices: routers, switches, radio, WAN links"),
    ("data",     "accent3", "databases, storage, data pipelines, message brokers"),
    ("security", "accent4", "firewalls, identity, PKI, security controls"),
    ("edge",     "accent5", "end-user and edge devices: browsers, phones, IoT, sensors"),
    ("app",      "accent6", "applications, APIs, user-facing software"),
    ("external", "dk2",     "external parties and systems outside our control"),
]


def _hex(c: str) -> str:
    return "#" + c.upper()


def _mix(c: str, other: str, t: float) -> str:
    a = [int(c[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b, strict=True))


def _lum(c: str) -> float:
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def role_from_colour(c: str) -> dict:
    """Light tint fill, the colour itself as border, a dark shade for text."""
    fill = _mix(c, "#FFFFFF", 0.85)
    font = _mix(c, "#000000", 0.45) if _lum(c) > 0.25 else c
    return {"fill": fill, "stroke": c, "font": font}


def read_theme(path: str) -> dict:
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if re.match(r"ppt/theme/theme\d+\.xml$", n))
        if not names:
            raise ValueError("no theme found in this file - is it a PowerPoint .pptx/.potx?")
        root = ET.fromstring(z.read(names[0]))
    colours, fonts = {}, {}
    scheme = root.find(f".//{A}clrScheme")
    for slot in SLOTS:
        el = scheme.find(f"{A}{slot}") if scheme is not None else None
        if el is None:
            continue
        srgb, sys = el.find(f"{A}srgbClr"), el.find(f"{A}sysClr")
        if srgb is not None:
            colours[slot] = _hex(srgb.get("val"))
        elif sys is not None and sys.get("lastClr"):
            colours[slot] = _hex(sys.get("lastClr"))
    for kind in ("majorFont", "minorFont"):
        el = root.find(f".//{A}fontScheme/{A}{kind}/{A}latin")
        if el is not None:
            fonts[kind] = el.get("typeface")
    return {"colours": colours, "fonts": fonts,
            "theme_name": scheme.get("name") if scheme is not None else ""}


def build_style(path: str) -> dict:
    th = read_theme(path)
    col = th["colours"]
    roles = {}
    for role, slot, desc in ROLE_MAP:
        c = col.get(slot)
        if not c:
            continue
        roles[role] = {**role_from_colour(c), "description": desc, "theme_slot": slot}
    phase_base = col.get("accent2") or col.get("accent1") or "#D85A30"
    roles["phase2"] = {**role_from_colour(phase_base), "dashed": True,
                       "description": "anything added in a later project phase (drawn dashed)",
                       "theme_slot": "accent2"}
    dark = col.get("dk2") or col.get("dk1") or "#333333"
    return {
        "source": path,
        "theme_name": th["theme_name"],
        "font": th["fonts"].get("minorFont") or "Helvetica",
        "font_size": 12,
        "rounded_boxes": True,
        "palette": col,
        "edge": {"color": _mix(dark, "#FFFFFF", 0.25), "font": dark},
        "container": {"fill": "none", "stroke": _mix(dark, "#FFFFFF", 0.45),
                      "font": dark, "dashed": True},
        "default_role": "primary",
        "roles": roles,
        "rules": [
            "Use sentence case for all labels.",
            "Keep each label to two short lines: a name, then a 2-5 word description.",
            "Group related components in a subgraph named after the layer or zone.",
            "Show later-phase components with the phase2 class.",
        ],
    }


def save_style(path: str, out: str) -> dict:
    style = build_style(path)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(style, f, indent=2)
    return style


def load_style(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
