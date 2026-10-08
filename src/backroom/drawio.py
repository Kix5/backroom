"""Write a laid-out Mermaid graph as an editable .drawio file and an SVG preview."""
from __future__ import annotations

import html
import uuid
import xml.etree.ElementTree as ET

from .layout import absolute, layout
from .mermaid import Graph

SHAPE_STYLE = {
    "rect": "",
    "round": "rounded=1;arcSize=20;",
    "stadium": "rounded=1;arcSize=50;",
    "cylinder": "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=8;",
    "subroutine": "shape=process;backgroundOutline=1;",
    "circle": "ellipse;",
    "hexagon": "shape=hexagon;perimeter=hexagonPerimeter2;size=0.12;",
    "diamond": "rhombus;",
    "parallelogram": "shape=parallelogram;perimeter=parallelogramPerimeter;size=0.12;",
    "flag": "shape=step;perimeter=stepPerimeter;size=0.1;",
}

DEFAULT_STYLE = {
    "font": "Helvetica",
    "font_size": 12,
    "rounded_boxes": True,
    "edge": {"color": "#5F5E5A", "font": "#444441"},
    "container": {"fill": "none", "stroke": "#888780", "font": "#2C2C2A", "dashed": True},
    "default_role": "primary",
    "roles": {
        "primary": {"fill": "#E6F1FB", "stroke": "#185FA5", "font": "#0C447C"},
    },
}


def role_colors(style: dict, graph: Graph, cls: str | None):
    roles = style.get("roles", {})
    if cls and cls in roles:
        return roles[cls]
    if cls and cls in graph.class_defs:
        cd = graph.class_defs[cls]
        base = roles.get(style.get("default_role"), {})
        return {"fill": cd.get("fill") or base.get("fill"),
                "stroke": cd.get("stroke") or base.get("stroke"),
                "font": cd.get("font") or base.get("font"),
                "dashed": cd.get("dashed")}
    return roles.get(style.get("default_role"), next(iter(roles.values()), {}))


def _html_label(text: str) -> str:
    return "<br>".join(html.escape(line) for line in text.split("\n"))


def to_drawio(graph: Graph, style: dict | None = None, page_name="Diagram") -> tuple[str, dict]:
    style = {**DEFAULT_STYLE, **(style or {})}
    boxes = layout(graph)
    font = style.get("font", "Helvetica")
    fsize = style.get("font_size", 12)

    mxfile = ET.Element("mxfile", host="backroom", type="device")
    diagram = ET.SubElement(mxfile, "diagram", name=page_name, id=uuid.uuid4().hex[:20])
    model = ET.SubElement(diagram, "mxGraphModel", dx="1200", dy="800", grid="1", gridSize="10",
                          guides="1", tooltips="1", connect="1", arrows="1", fold="1", page="0",
                          pageScale="1", math="0", shadow="0")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    def cid(k):
        return ("g_" if k in graph.groups else "n_") + k

    def parent_id(b):
        return "g_" + b.parent if b.parent else "1"

    def geom(cell, b):
        ET.SubElement(cell, "mxGeometry", x=str(b.x), y=str(b.y), width=str(b.w),
                      height=str(b.h), **{"as": "geometry"})

    # containers, parents before children
    def depth(gid):
        d = 0
        while graph.groups[gid].parent:
            gid, d = graph.groups[gid].parent, d + 1
        return d

    cont = style.get("container", {})
    for gid in sorted(graph.groups, key=depth):
        grp, b = graph.groups[gid], boxes[gid]
        c = role_colors(style, graph, grp.cls) if grp.cls else cont
        fill = c.get("fill", "none")
        s = (f"rounded=1;arcSize=4;whiteSpace=wrap;html=1;container=1;collapsible=0;"
             f"verticalAlign=top;align=left;spacingLeft=10;spacingTop=4;fontStyle=1;"
             f"fillColor={fill};strokeColor={c.get('stroke', '#888780')};"
             f"fontColor={c.get('font', '#2C2C2A')};fontFamily={font};fontSize={fsize + 1};"
             + ("dashed=1;" if cont.get("dashed", True) or c.get("dashed") else ""))
        cell = ET.SubElement(root, "mxCell", id=cid(gid), value=_html_label(grp.title),
                             style=s, vertex="1", parent=parent_id(b))
        geom(cell, b)

    for nid, n in graph.nodes.items():
        b = boxes[nid]
        c = role_colors(style, graph, n.cls)
        shape = n.shape
        base = SHAPE_STYLE.get(shape, "")
        if shape == "rect" and style.get("rounded_boxes", True):
            base = "rounded=1;arcSize=10;"
        s = (base + "whiteSpace=wrap;html=1;"
             f"fillColor={c.get('fill', '#FFFFFF')};strokeColor={c.get('stroke', '#333333')};"
             f"fontColor={c.get('font', '#000000')};fontFamily={font};fontSize={fsize};"
             + ("dashed=1;" if c.get("dashed") else ""))
        label = n.label
        if "\n" in label:  # first line bold = title, rest = subtitle
            first, rest = label.split("\n", 1)
            value = f"<b>{html.escape(first)}</b><br>" + _html_label(rest)
        else:
            value = f"<b>{html.escape(label)}</b>"
        cell = ET.SubElement(root, "mxCell", id=cid(nid), value=value, style=s, vertex="1",
                             parent=parent_id(b))
        geom(cell, b)

    ec = style.get("edge", {})
    for i, e in enumerate(graph.edges):
        s = ("edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;"
             f"strokeColor={ec.get('color', '#5F5E5A')};fontColor={ec.get('font', '#444441')};"
             f"fontFamily={font};fontSize={fsize - 1};labelBackgroundColor=#FFFFFF;")
        s += "endArrow=block;endFill=1;" if e.arrow_end else "endArrow=none;"
        if e.arrow_start:
            s += "startArrow=block;startFill=1;"
        if e.style == "dotted":
            s += "dashed=1;"
        elif e.style == "thick":
            s += "strokeWidth=2.5;"
        cell = ET.SubElement(root, "mxCell", id=f"e_{i}", value=_html_label(e.label), style=s,
                             edge="1", parent="1", source=cid(e.src), target=cid(e.dst))
        ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})

    ET.indent(mxfile)
    return ET.tostring(mxfile, encoding="unicode"), boxes


# ------------------------------------------------------------------ preview --
def to_svg(graph: Graph, boxes: dict, style: dict | None = None) -> str:
    """Quick static preview (straight connectors). The .drawio file is the real output."""
    style = {**DEFAULT_STYLE, **(style or {})}
    ab = absolute(boxes)
    W = max(ab[k][0] + boxes[k].w for k in boxes) + 40
    H = max(ab[k][1] + boxes[k].h for k in boxes) + 40
    font = html.escape(style.get("font", "Helvetica"))
    fs = style.get("font_size", 12)
    out = [(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="{font}, Helvetica, Arial, sans-serif">'),
           ('<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
           'markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" '
           f'fill="{style["edge"].get("color", "#555")}"/></marker></defs>'),
           f'<rect width="{W:.0f}" height="{H:.0f}" fill="#FFFFFF"/>']
    cont = style.get("container", {})

    def depth(gid):
        d = 0
        while graph.groups[gid].parent:
            gid, d = graph.groups[gid].parent, d + 1
        return d

    for gid in sorted(graph.groups, key=depth):
        (x, y), b = ab[gid], boxes[gid]
        c = role_colors(style, graph, graph.groups[gid].cls) if graph.groups[gid].cls else cont
        fill = c.get("fill", "none")
        out.append(f'<rect x="{x}" y="{y}" width="{b.w}" height="{b.h}" rx="8" fill="{fill}" '
                   f'stroke="{c.get("stroke", "#888")}" stroke-dasharray="6 4"/>')
        out.append(f'<text x="{x + 12}" y="{y + 20}" font-size="{fs + 1}" font-weight="bold" '
                   f'fill="{c.get("font", "#222")}">{html.escape(graph.groups[gid].title)}</text>')

    def centre(k):
        (x, y), b = ab[k], boxes[k]
        return x + b.w / 2, y + b.h / 2, b

    def clip(cx, cy, b, tx, ty):
        dx, dy = tx - cx, ty - cy
        if dx == dy == 0:
            return cx, cy
        sx = (b.w / 2) / abs(dx) if dx else float("inf")
        sy = (b.h / 2) / abs(dy) if dy else float("inf")
        s = min(sx, sy)
        return cx + dx * s, cy + dy * s

    for e in graph.edges:
        x1, y1, b1 = centre(e.src)
        x2, y2, b2 = centre(e.dst)
        sx, sy = clip(x1, y1, b1, x2, y2)
        tx, ty = clip(x2, y2, b2, x1, y1)
        dash = ' stroke-dasharray="5 4"' if e.style == "dotted" else ""
        sw = 2.5 if e.style == "thick" else 1.2
        me = ' marker-end="url(#a)"' if e.arrow_end else ""
        ms = ' marker-start="url(#a)"' if e.arrow_start else ""
        out.append(f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" '
                   f'stroke="{style["edge"].get("color", "#555")}" stroke-width="{sw}"{dash}{me}{ms}/>')
        if e.label:
            mx, my = (sx + tx) / 2, (sy + ty) / 2
            lw = len(e.label) * (fs - 1) * 0.6 + 8
            out.append(f'<rect x="{mx - lw / 2:.1f}" y="{my - fs:.1f}" width="{lw:.1f}" '
                       f'height="{fs + 6}" fill="#FFFFFF"/>')
            out.append(f'<text x="{mx:.1f}" y="{my + 1:.1f}" font-size="{fs - 1}" '
                       f'text-anchor="middle" fill="#444">{html.escape(e.label)}</text>')

    for nid, n in graph.nodes.items():
        (x, y), b = ab[nid], boxes[nid]
        c = role_colors(style, graph, n.cls)
        dash = ' stroke-dasharray="5 3"' if c.get("dashed") else ""
        if n.shape == "diamond":
            pts = f"{x + b.w / 2},{y} {x + b.w},{y + b.h / 2} {x + b.w / 2},{y + b.h} {x},{y + b.h / 2}"
            out.append(f'<polygon points="{pts}" fill="{c.get("fill")}" stroke="{c.get("stroke")}"{dash}/>')
        elif n.shape == "circle":
            out.append(f'<ellipse cx="{x + b.w / 2}" cy="{y + b.h / 2}" rx="{b.w / 2}" ry="{b.h / 2}" '
                       f'fill="{c.get("fill")}" stroke="{c.get("stroke")}"{dash}/>')
        else:
            rounded = style.get("rounded_boxes", True) or n.shape == "round"
            rx = b.h / 2 if n.shape == "stadium" else (6 if rounded else 0)
            out.append(f'<rect x="{x}" y="{y}" width="{b.w}" height="{b.h}" rx="{rx}" '
                       f'fill="{c.get("fill")}" stroke="{c.get("stroke")}"{dash}/>')
        lines = n.label.split("\n")
        y0 = y + b.h / 2 - (len(lines) - 1) * 8 + 4
        for i, line in enumerate(lines):
            weight = ' font-weight="bold"' if i == 0 else ""
            out.append(f'<text x="{x + b.w / 2}" y="{y0 + i * 16:.1f}" font-size="{fs}" text-anchor="middle" '
                       f'fill="{c.get("font")}"{weight}>{html.escape(line)}</text>')
    out.append("</svg>")
    return "\n".join(out)
