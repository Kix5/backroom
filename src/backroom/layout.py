"""Compound layered layout for parsed Mermaid flowcharts.

Each subgraph is laid out recursively: its children (nodes and nested
subgraphs) are ranked along the flow direction using the edges between them,
ordered to reduce crossings, then packed. A subgraph's size is the bounding
box of its children plus padding, so containers never overlap.

All positions are *relative to the parent container*, which is exactly what
draw.io expects for cells inside a container.
"""
from __future__ import annotations

from dataclasses import dataclass

from .mermaid import Graph

NODE_MIN_W, NODE_H, LINE_H, CHAR_W = 130, 46, 16, 7.2
GAP_ACROSS, GAP_FLOW = 36, 64
PAD, TITLE_H = 22, 30
MAX_PER_RANK = 6


@dataclass
class Box:
    id: str
    kind: str          # node | group
    x: float = 0.0     # relative to parent content
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    parent: str | None = None


def node_size(label: str, shape: str):
    lines = label.split("\n") or [""]
    w = max(NODE_MIN_W, max(len(line) for line in lines) * CHAR_W + 34)
    h = NODE_H + (len(lines) - 1) * LINE_H
    if shape in ("diamond",):
        w, h = w * 1.35, h * 1.5
    elif shape in ("hexagon", "parallelogram"):
        w *= 1.15
    elif shape == "circle":
        w = h = max(w, h)
    elif shape == "cylinder":
        h += 14
    return round(w), round(h)


def layout(g: Graph) -> dict[str, Box]:
    boxes: dict[str, Box] = {}

    # owner chain helpers
    def group_of(item):
        if item in g.nodes:
            return g.nodes[item].group
        return g.groups[item].parent

    def ancestor_in(item, gid):
        """The direct child of gid that contains item (or None if outside gid)."""
        cur = item
        while cur is not None:
            parent = group_of(cur)
            if parent == gid:
                return cur
            cur = parent
        return None

    def direction_of(gid):
        while gid is not None:
            d = g.groups[gid].direction
            if d:
                return d
            gid = g.groups[gid].parent
        return g.direction

    def place(gid):
        nodes, groups = g.items_in(gid)
        for sub in groups:
            place(sub)
        items = nodes + groups
        # keep declaration order: nodes and groups interleaved by first appearance
        order_hint = {k: i for i, k in enumerate(list(g.nodes) + list(g.groups))}
        items.sort(key=lambda k: order_hint[k])
        for n in nodes:
            w, h = node_size(g.nodes[n].label, g.nodes[n].shape)
            boxes[n] = Box(n, "node", w=w, h=h, parent=gid)

        # child-level edges
        succ = {k: [] for k in items}
        pred = {k: [] for k in items}
        seen = set()
        for e in g.edges:
            a, b = ancestor_in(e.src, gid), ancestor_in(e.dst, gid)
            if a is None or b is None or a == b or (a, b) in seen:
                continue
            seen.add((a, b))
            succ[a].append(b)
            pred[b].append(a)

        # break cycles (DFS, drop back edges)
        state, dag = {}, {k: [] for k in items}

        def dfs(u):
            state[u] = 1
            for v in succ[u]:
                if state.get(v) == 1:
                    continue  # back edge
                dag[u].append(v)
                if v not in state:
                    dfs(v)
            state[u] = 2

        for k in items:
            if k not in state:
                dfs(k)
        rank = {k: 0 for k in items}
        changed = True
        while changed:  # longest path
            changed = False
            for u in items:
                for v in dag[u]:
                    if rank[v] < rank[u] + 1:
                        rank[v] = rank[u] + 1
                        changed = True
        # pull pure sources forward so they sit just before what they feed
        for u in items:
            if not any(u in dag[v] for v in items) and dag[u]:
                rank[u] = max(rank[u], min(rank[v] for v in dag[u]) - 1)
        nranks = max(rank.values()) + 1 if items else 0
        layers = [[k for k in items if rank[k] == r] for r in range(nranks)]

        # wrap very wide layers of unconnected items
        wrapped = []
        for layer in layers:
            if len(layer) > MAX_PER_RANK and all(not succ[k] and not pred[k] for k in layer):
                for i in range(0, len(layer), MAX_PER_RANK):
                    wrapped.append(layer[i:i + MAX_PER_RANK])
            else:
                wrapped.append(layer)
        layers = wrapped

        # barycenter ordering
        pos = {}
        for layer in layers:
            for i, k in enumerate(layer):
                pos[k] = i
        undirected = {k: set(succ[k]) | set(pred[k]) for k in items}
        for sweep in range(6):
            seq = layers if sweep % 2 == 0 else list(reversed(layers))
            for layer in seq[1:]:
                def bary(k, layer=layer):
                    nb = [pos[n] for n in undirected[k] if n in pos and n not in layer]
                    return sum(nb) / len(nb) if nb else pos[k]
                layer.sort(key=lambda k: (bary(k), pos[k]))
                for i, k in enumerate(layer):
                    pos[k] = i

        d = direction_of(gid)
        if gid is not None and not seen and len(items) > 1:
            # unconnected siblings (e.g. a list of zones): stack them across the
            # parent's flow so incoming links fan out cleanly instead of crossing
            d = direction_of(g.groups[gid].parent)
        horizontal = d in ("LR", "RL")

        def along(k):   # size along flow
            return boxes[k].w if horizontal else boxes[k].h

        def across(k):
            return boxes[k].h if horizontal else boxes[k].w

        widths = [sum(across(k) for k in L) + GAP_ACROSS * (len(L) - 1) for L in layers]
        max_across = max(widths) if widths else 0
        f = 0.0
        for L, wL in zip(layers, widths, strict=True):
            thick = max(along(k) for k in L)
            c = (max_across - wL) / 2
            for k in L:
                fa = f + (thick - along(k)) / 2
                if horizontal:
                    boxes[k].x, boxes[k].y = fa, c
                else:
                    boxes[k].x, boxes[k].y = c, fa
                c += across(k) + GAP_ACROSS
            f += thick + GAP_FLOW
        total_flow = f - GAP_FLOW if layers else 0

        if d in ("BT", "RL"):  # mirror along flow axis
            for k in items:
                if horizontal:
                    boxes[k].x = total_flow - boxes[k].x - boxes[k].w
                else:
                    boxes[k].y = total_flow - boxes[k].y - boxes[k].h

        cw, ch = (total_flow, max_across) if horizontal else (max_across, total_flow)
        if gid is not None:
            off_y = PAD + TITLE_H
            for k in items:
                boxes[k].x += PAD
                boxes[k].y += off_y
            title_w = len(g.groups[gid].title) * 7.6 + 2 * PAD
            boxes[gid] = Box(gid, "group", w=round(max(cw + 2 * PAD, title_w)),
                             h=round(ch + off_y + PAD), parent=g.groups[gid].parent)
            # centre content if the title made the box wider
            extra = boxes[gid].w - (cw + 2 * PAD)
            if extra > 0:
                for k in items:
                    boxes[k].x += extra / 2
        else:
            for k in items:
                boxes[k].x += 40
                boxes[k].y += 40
        for k in items:
            boxes[k].x, boxes[k].y = round(boxes[k].x), round(boxes[k].y)

    place(None)
    return boxes


def absolute(boxes: dict[str, Box]):
    """Absolute (x, y) of every box, summing parent offsets."""
    out = {}

    def ab(k):
        if k in out:
            return out[k]
        b = boxes[k]
        if b.parent is None:
            out[k] = (b.x, b.y)
        else:
            px, py = ab(b.parent)
            out[k] = (px + b.x, py + b.y)
        return out[k]

    for k in boxes:
        ab(k)
    return out
