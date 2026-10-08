import xml.etree.ElementTree as ET
from itertools import combinations
from pathlib import Path

from backroom.drawio import to_drawio, to_svg
from backroom.layout import absolute, layout
from backroom.mermaid import parse

EXAMPLE = Path(__file__).parent.parent / "examples" / "web_app.mmd"


def overlaps(a, b):
    (ax, ay, aw, ah), (bx, by, bw, bh) = a, b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def test_siblings_never_overlap_and_containers_hold_children():
    g = parse(EXAMPLE.read_text())
    boxes = layout(g)
    ab = absolute(boxes)
    rect = {k: (ab[k][0], ab[k][1], boxes[k].w, boxes[k].h) for k in boxes}
    by_parent = {}
    for k, b in boxes.items():
        by_parent.setdefault(b.parent, []).append(k)
    for kids in by_parent.values():
        for a, b in combinations(kids, 2):
            assert not overlaps(rect[a], rect[b]), (a, b)
    for k, b in boxes.items():
        if b.parent:
            px, py, pw, ph = rect[b.parent]
            x, y, w, h = rect[k]
            assert px <= x and py <= y and x + w <= px + pw and y + h <= py + ph, k


def test_unconnected_group_stacks_across_parent_flow():
    g = parse("""flowchart LR
      hub --> z1 & z2 & z3
      subgraph zones["Zones"]
        z1
        z2
        z3
      end""")
    boxes = layout(g)
    xs = {boxes[z].x for z in ("z1", "z2", "z3")}
    assert len(xs) == 1  # one column: stacked vertically in an LR diagram


def test_flow_direction_respected():
    g = parse("flowchart LR\n a --> b --> c")
    b = layout(g)
    assert b["a"].x < b["b"].x < b["c"].x
    g = parse("flowchart BT\n a --> b")
    b = layout(g)
    assert b["a"].y > b["b"].y


def test_drawio_xml_is_valid_and_complete():
    g = parse(EXAMPLE.read_text())
    style = {"roles": {"app": {"fill": "#EEEEFF", "stroke": "#3333AA", "font": "#111155"},
                       "phase2": {"fill": "#FFF", "stroke": "#A60", "font": "#630", "dashed": True}},
             "default_role": "app", "font": "Arial"}
    xml, _ = to_drawio(g, style)
    root = ET.fromstring(xml)
    cells = root.findall(".//mxCell")
    ids = {c.get("id") for c in cells}
    assert len(ids) == len(cells)
    for c in cells:
        if c.get("parent"):
            assert c.get("parent") in ids
        if c.get("edge"):
            assert c.get("source") in ids and c.get("target") in ids
    vertices = [c for c in cells if c.get("vertex")]
    assert len(vertices) == len(g.nodes) + len(g.groups)
    assert len([c for c in cells if c.get("edge")]) == len(g.edges)
    search = next(c for c in cells if c.get("id") == "n_search")
    assert "dashed=1" in search.get("style") and "fontFamily=Arial" in search.get("style")
    # children of a container are parented to it (so they move with it in draw.io)
    assert next(c for c in cells if c.get("id") == "n_orders").get("parent") == "g_services"


def test_label_markup_is_escaped():
    g = parse('flowchart TD\n a["<script> & co<br/>x < y"]')
    xml, _ = to_drawio(g)
    value = ET.fromstring(xml).find(".//mxCell[@id='n_a']").get("value")
    assert "<script>" not in value and "&lt;script&gt; &amp; co" in value


def test_svg_preview_is_valid_xml():
    g = parse(EXAMPLE.read_text())
    _xml, boxes = to_drawio(g)
    ET.fromstring(to_svg(g, boxes))
