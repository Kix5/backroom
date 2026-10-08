import pytest

from backroom.mermaid import MermaidError, extract_mermaid, parse


def test_header_and_direction():
    assert parse("flowchart LR\n a").direction == "LR"
    assert parse("graph TD\n a").direction == "TB"
    assert parse("flowchart\n a").direction == "TB"


@pytest.mark.parametrize("src,shape", [
    ('a["x"]', "rect"), ('a("x")', "round"), ('a(["x"])', "stadium"), ('a[("x")]', "cylinder"),
    ('a[["x"]]', "subroutine"), ('a(("x"))', "circle"), ('a{"x"}', "diamond"),
    ('a{{"x"}}', "hexagon"), ('a[/"x"/]', "parallelogram"), ('a>"x"]', "flag"),
])
def test_shapes(src, shape):
    n = parse(f"flowchart TD\n  {src}").nodes["a"]
    assert n.shape == shape and n.label == "x"


def test_labels_with_brackets_inside_quotes_and_line_breaks():
    n = parse('flowchart TD\n a["Core (HA) [pair]<br/>second line"]').nodes["a"]
    assert n.label == "Core (HA) [pair]\nsecond line"


def test_edges_styles_labels_and_chains():
    g = parse("""flowchart LR
      a --> b -.-> c ==> d
      a ---|plain| d
      b <-->|sync| c
      c -- yes --> a
    """)
    kinds = [(e.src, e.dst, e.style, e.arrow_end, e.arrow_start, e.label) for e in g.edges]
    assert ("a", "b", "solid", True, False, "") in kinds
    assert ("b", "c", "dotted", True, False, "") in kinds
    assert ("c", "d", "thick", True, False, "") in kinds
    assert ("a", "d", "solid", False, False, "plain") in kinds
    assert ("b", "c", "solid", True, True, "sync") in kinds
    assert ("c", "a", "solid", True, False, "yes") in kinds


def test_fan_out_with_ampersand():
    g = parse("flowchart LR\n a & b --> c & d")
    assert {(e.src, e.dst) for e in g.edges} == {("a", "c"), ("a", "d"), ("b", "c"), ("b", "d")}


def test_nested_subgraphs_direction_and_classes():
    g = parse("""flowchart LR
      subgraph outer["Outer box"]
        direction TB
        a["A"]:::app
        subgraph inner["Inner"]
          b["B"]
        end
      end
      c --> inner
      class c data
      classDef app fill:#fff,stroke:#000
    """)
    assert g.groups["outer"].direction == "TB"
    assert g.groups["inner"].parent == "outer"
    assert g.nodes["a"].group == "outer" and g.nodes["b"].group == "inner"
    assert g.nodes["a"].cls == "app" and g.nodes["c"].cls == "data"
    assert "inner" not in g.nodes  # an edge to a subgraph targets the container
    assert g.edges[0].dst == "inner"
    assert g.class_defs["app"]["fill"] == "#fff"


def test_ignores_comments_and_styling_statements():
    g = parse("flowchart TD\n %% note\n a --> b\n style a fill:#f00\n linkStyle 0 stroke:#f00\n click a href")
    assert len(g.nodes) == 2 and len(g.edges) == 1


@pytest.mark.parametrize("src,msg", [
    ("sequenceDiagram\n a->>b: hi", "must start"),
    ("flowchart TD\n subgraph x\n a", "missing its 'end'"),
    ("flowchart TD\n end", "without a matching"),
    ('flowchart TD\n a["open', "unclosed quote"),
    ("flowchart TD\n a ~~ b", "could not understand"),
    ("flowchart TD\n a\n class zz app", "unknown id"),
])
def test_errors_are_reported_with_reason(src, msg):
    with pytest.raises(MermaidError) as e:
        parse(src)
    assert msg in str(e.value)


def test_extract_mermaid_from_model_reply():
    reply = "<think>hmm</think>Here you go:\n```mermaid\nflowchart TD\n a --> b\n```\nDone."
    assert extract_mermaid(reply) == "flowchart TD\n a --> b"
    assert extract_mermaid("flowchart LR\n a --> b") == "flowchart LR\n a --> b"
