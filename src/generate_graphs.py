"""
Benchmark generator (v5): ground truth built on REAL JGraphT base graphs.

Pipeline
--------
1. Java (GenerateBase.java, JGraphT) writes the base structure of each graph
   to JSON files (folder given by --base).
2. This script reads those files and adds everything else: node and edge
   labels, shuffled node ids, edge directions, Cypher, meta.json.

Design rules (DECISIONS.md)
---------------------------
- GROWTH CHAINS (D3, D13). For the NESTED families (chain, star, tree, grid,
  bipartite, complete, sparse, dense, scale_free) the Java file holds the
  biggest graph, numbered so that every prefix is connected. The graph with k
  nodes is the first k nodes and the edges between them. Labels and edge
  directions depend only on node indices and the seed, so a node or edge keeps
  its label and direction in every bigger graph.
  Cycle, wheel and small_world are INDEPENDENT: one Java file per size.
  meta.json says which case applies ("nested": true/false).
- CONNECTED ONLY (D13). Checked for every sample.
- SAME GRAPH, DIRECTED OR NOT (D4). The two variants are identical except
  for the "directed" flag.
- SELF-LOOPS are a switch, off by default (D5).

Output per sample:
    sample_XXXXXX/
        graph.json     ground truth (schema below)
        graph.cypher   ground-truth Cypher, with sample_id on every node/edge
        meta.json      seed, family, parameters, statistics, index_to_id
plus one manifest.csv in the output folder listing every sample.

graph.json schema
-----------------
{
  "directed": true,
  "nodes": [{"id": "n1", "label": "Person"}, ...],
  "edges": [{"source": "n1", "target": "n2", "label": "LIVES_IN"}, ...]
}

Rules
-----
- Node ids are "n1".."nN", shuffled per graph. meta.json -> index_to_id gives
  the creation order, which is how nodes are paired across sizes.
- Node and edge labels come from small fixed vocabularies, assigned randomly
  but stably.
- At most one edge per node pair; the graph is connected.
- Undirected graphs are stored once in arbitrary direction (Cypher cannot
  store undirected edges); the evaluation must ignore direction for them.
- Natural direction for chain, star, tree, grid (earlier -> later node), cycle
  (around the cycle) and wheel (hub -> rim, rim around). Random orientation,
  fixed per edge, for the other families.

Requires: networkx (pip install networkx).

Usage
-----
    python generate_graphs.py --base DIR --selftest
    python generate_graphs.py --base DIR --out samples --pilot
    python generate_graphs.py --base DIR --out samples --grid
    python generate_graphs.py --base DIR --out samples --grid --sizes 10 50 200 --seeds 5
    python generate_graphs.py --base DIR --out samples_loops --grid --self-loop-rate 0.1
    python generate_graphs.py --base DIR --out samples --family grid --nodes 100 --seed 1 --directed

DIR is the folder written by GenerateBase.java. Run Java with the same seeds
and sizes you ask for here (a sample whose base file is missing is skipped
and reported).
"""

import argparse
import csv
import json
import random
from functools import lru_cache
from pathlib import Path

import networkx as nx

NODE_LABELS = ["Person", "City", "Company", "Product", "Event"]
EDGE_LABELS = ["KNOWS", "LIVES_IN", "WORKS_AT", "OWNS", "LOCATED_IN"]

# family -> (JGraphT generator used in the Java file, default max nodes in the grid)
FAMILIES = {
    "chain":       ("LinearGraphGenerator", 500),
    "star":        ("StarGraphGenerator", 500),
    "cycle":       ("RingGraphGenerator", 500),
    "wheel":       ("WheelGraphGenerator", 200),
    "tree":        ("random attachment tree (not in JGraphT)", 500),
    "grid":        ("GridGraphGenerator", 500),
    "bipartite":   ("CompleteBipartiteGraphGenerator", 60),
    "complete":    ("CompleteGraphGenerator", 40),
    "sparse":      ("GnmRandomGraphGenerator", 500),
    "dense":       ("GnpRandomGraphGenerator", 100),
    "scale_free":  ("BarabasiAlbertGraphGenerator", 500),
    "small_world": ("WattsStrogatzGraphGenerator", 500),
}
NESTED = {"chain", "star", "tree", "grid", "bipartite", "complete",
          "sparse", "dense", "scale_free"}
NATURAL_DIRECTION = {"chain", "star", "tree", "grid", "cycle", "wheel"}
MIN_NODES = {"cycle": 3, "wheel": 4, "grid": 4, "small_world": 5, "scale_free": 3}
DEFAULT_SIZES = [5, 10, 15, 20, 30, 40, 50, 75, 100, 150, 200, 300, 500]


class BaseMissing(Exception):
    """The Java base file for this sample does not exist (or is too small)."""


def _rng(*parts):
    """Deterministic random generator keyed by a tuple (independent of graph size)."""
    return random.Random("|".join(str(p) for p in parts))


# --------------------------------------------------------------------------
# Reading the Java base files
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_base(base_dir, family, seed, n):
    """Returns (edges, data): edges as (u, v) on nodes 0..n-1, data = the JSON."""
    if family in NESTED:
        path = Path(base_dir) / f"{family}_seed{seed}.json"
    else:
        path = Path(base_dir) / f"{family}_seed{seed}_n{n}.json"
    if not path.exists():
        raise BaseMissing(path.name)
    data = _read_json(str(path))
    if family in NESTED:
        if n > data["n"]:
            raise BaseMissing(f"{path.name} has {data['n']} nodes, {n} needed")
        edges = [(a, b) for a, b in data["edges"] if b < n]   # a < b by construction
    else:
        if data["n"] != n:
            raise BaseMissing(f"{path.name} has {data['n']} nodes, {n} needed")
        edges = [(a, b) for a, b in data["edges"]]
    return edges, data


# --------------------------------------------------------------------------
# Edge directions
# --------------------------------------------------------------------------
def _walk(nodes, adj):
    """Walk around a cycle: start at the smallest node, always step to the
    smallest unvisited neighbour (inside `nodes`)."""
    nodes = set(nodes)
    seq = [min(nodes)]
    seen = {seq[0]}
    while True:
        nxt = sorted(x for x in adj[seq[-1]] if x in nodes and x not in seen)
        if not nxt:
            return seq
        seq.append(nxt[0])
        seen.add(nxt[0])


def orient(family, seed, edges, n):
    """List of (source, target) index pairs, one per edge."""
    adj = {i: set() for i in range(n)}
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)
    if family == "cycle":
        seq = _walk(range(n), adj)
        assert len(seq) == n, "cycle base graph is not a single cycle"
        return [(seq[i], seq[(i + 1) % n]) for i in range(n)]
    if family == "wheel":
        hub = max(range(n), key=lambda i: (len(adj[i]), -i))
        rim_nodes = [i for i in range(n) if i != hub]
        rim_adj = {i: adj[i] - {hub} for i in rim_nodes}
        seq = _walk(rim_nodes, rim_adj)
        assert len(seq) == n - 1, "wheel base graph has no single rim"
        out = [(hub, r) for r in rim_nodes]
        out += [(seq[i], seq[(i + 1) % len(seq)]) for i in range(len(seq))]
        return out
    if family in NATURAL_DIRECTION:          # nested: earlier -> later
        return [(min(u, v), max(u, v)) for u, v in edges]
    out = []
    for u, v in edges:
        a, b = min(u, v), max(u, v)
        flip = _rng(seed, family, "dir", a, b).random() < 0.5
        out.append((b, a) if flip else (a, b))
    return out


# --------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------
def generate_graph(family, n_nodes, seed, directed=True, self_loop_rate=0.0,
                   base_dir="base"):
    """Returns (graph, index_to_id). index_to_id[i] is the id of creation index i."""
    if n_nodes < MIN_NODES.get(family, 2):
        raise ValueError(f"{family} needs at least {MIN_NODES.get(family, 2)} nodes")
    n = n_nodes
    edges, _ = load_base(base_dir, family, seed, n)
    oriented = orient(family, seed, edges, n)

    perm = list(range(n))
    _rng(seed, family, "ids", n).shuffle(perm)
    index_to_id = [f"n{perm[i] + 1}" for i in range(n)]

    nodes = [{"id": index_to_id[i],
              "label": _rng(seed, family, "node", i).choice(NODE_LABELS)}
             for i in range(n)]
    nodes.sort(key=lambda d: int(d["id"][1:]))

    def edge_label(a, b):
        return _rng(seed, family, "edge", min(a, b), max(a, b)).choice(EDGE_LABELS)

    out_edges = [{"source": index_to_id[u], "target": index_to_id[v],
                  "label": edge_label(u, v)} for u, v in oriented]
    if self_loop_rate > 0:
        for i in range(n):
            if _rng(seed, family, "loop", i).random() < self_loop_rate:
                out_edges.append({"source": index_to_id[i], "target": index_to_id[i],
                                  "label": edge_label(i, i)})
    out_edges.sort(key=lambda e: (int(e["source"][1:]), int(e["target"][1:])))

    graph = {"directed": directed, "nodes": nodes, "edges": out_edges}
    validate(graph)
    return graph, index_to_id


def validate(graph):
    node_ids = [n["id"] for n in graph["nodes"]]
    assert len(set(node_ids)) == len(node_ids), "duplicate node ids"
    seen = set()
    for e in graph["edges"]:
        assert e["source"] in node_ids and e["target"] in node_ids, "dangling edge"
        pair = frozenset((e["source"], e["target"]))  # one edge per pair (loop = 1 node)
        assert pair not in seen, "duplicate edge"
        seen.add(pair)
    assert nx.is_connected(to_networkx(graph).to_undirected()), "graph not connected"


def to_networkx(graph):
    g = nx.DiGraph() if graph["directed"] else nx.Graph()
    for n in graph["nodes"]:
        g.add_node(n["id"], label=n["label"])
    for e in graph["edges"]:
        g.add_edge(e["source"], e["target"], label=e["label"])
    return g


def to_cypher(graph, sample_id):
    """One deterministic CREATE statement; sample_id on every node and edge."""
    sid = f'sample_id: "{sample_id}"'
    parts = [f'({n["id"]}:{n["label"]} {{id: "{n["id"]}", {sid}}})'
             for n in graph["nodes"]]
    parts += [f'({e["source"]})-[:{e["label"]} {{{sid}}}]->({e["target"]})'
              for e in graph["edges"]]
    return "CREATE\n  " + ",\n  ".join(parts) + ";\n"


# --------------------------------------------------------------------------
# Self-test of the design rules
# --------------------------------------------------------------------------
def _by_index(graph, index_to_id):
    inv = {v: i for i, v in enumerate(index_to_id)}
    nodes = {inv[n["id"]]: n["label"] for n in graph["nodes"]}
    edges = {(inv[e["source"]], inv[e["target"]], e["label"]) for e in graph["edges"]}
    return nodes, edges


def selftest(base_dir, seeds=(1, 2, 3), sizes=(5, 10, 15, 20, 30, 40), loop_rate=0.2):
    """Checks (1) smaller graphs sit inside bigger ones, (2) directed and
    undirected variants are the same graph, (3) every graph is connected,
    (4) cycle and wheel directions are the natural ones.
    Samples whose base file is missing are skipped. Returns the number of failures."""
    fails = checked = 0
    for family in FAMILIES:
        for seed in seeds:
            ok_nested = True
            for rate in (0.0, loop_rate):
                prev = None
                for n in sizes:
                    if n < MIN_NODES.get(family, 2):
                        continue
                    try:
                        gd, ids = generate_graph(family, n, seed, True, rate, base_dir)
                        gu, _ = generate_graph(family, n, seed, False, rate, base_dir)
                    except BaseMissing:
                        continue
                    checked += 1
                    if gd["nodes"] != gu["nodes"] or gd["edges"] != gu["edges"]:
                        print(f"FAIL pair {family} seed={seed} n={n}")
                        fails += 1
                    if family == "cycle" and rate == 0:
                        d = to_networkx(gd)
                        if not all(d.in_degree(x) == 1 and d.out_degree(x) == 1 for x in d):
                            print(f"FAIL cycle direction seed={seed} n={n}")
                            fails += 1
                    nodes, edges = _by_index(gd, ids)
                    if prev and family in NESTED:
                        pn, pe, pcount = prev
                        sub_nodes = {i: l for i, l in nodes.items() if i < pcount}
                        sub_edges = {e for e in edges if e[0] < pcount and e[1] < pcount}
                        if sub_nodes != pn or sub_edges != pe:
                            ok_nested = False
                    prev = (nodes, edges, n)
            if not ok_nested:
                print(f"FAIL nesting {family} seed={seed}")
                fails += 1
    if checked == 0:
        print("selftest: no base files found, check --base")
        return 1
    print(f"selftest: {checked} graphs checked,",
          "all checks passed" if not fails else f"{fails} FAILURES")
    return fails


# --------------------------------------------------------------------------
# Writing samples
# --------------------------------------------------------------------------
def write_sample(out_dir, base_dir, index, family, n_nodes, seed, directed,
                 self_loop_rate=0.0):
    graph, index_to_id = generate_graph(family, n_nodes, seed, directed,
                                        self_loop_rate, base_dir)
    _, base = load_base(base_dir, family, seed, n_nodes)
    sample_id = f"sample_{index:06d}"
    folder = Path(out_dir) / sample_id
    folder.mkdir(parents=True, exist_ok=True)

    n, m = len(graph["nodes"]), len(graph["edges"])
    loops = sum(e["source"] == e["target"] for e in graph["edges"])
    meta = {
        "sample_id": sample_id,
        "family": family,
        "jgrapht_generator": base["jgrapht_generator"],
        "base_note": base["note"],
        "nested": family in NESTED,
        "chain": f"{family}_seed{seed}",  # same chain + same n = directed/undirected pair
        "seed": seed,
        "directed": directed,
        "n_nodes": n,
        "n_edges": m,
        "n_self_loops": loops,
        "self_loop_rate": self_loop_rate,
        "density": round((m - loops) / (n * (n - 1) / 2), 4),
        "index_to_id": index_to_id,
        "node_label_vocab": NODE_LABELS,
        "edge_label_vocab": EDGE_LABELS,
        "split": None,       # dev / test / train, set when splits are assigned
        "rendering": None,   # filled by the renderer
        "overlaps": None,    # filled by the overlap counter
    }
    (folder / "graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")
    (folder / "graph.cypher").write_text(to_cypher(graph, sample_id), encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def generate_grid(out_dir, base_dir, families, sizes, seeds, respect_caps=True,
                  self_loop_rate=0.0):
    """families x seeds x sizes x {directed, undirected}, plus manifest.csv."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rows, skipped, index = [], [], 1  # sample_000001, sample_000002, ...
    for family in families:
        cap = FAMILIES[family][1]
        for seed in range(1, seeds + 1):
            for n in sizes:
                if (respect_caps and n > cap) or n < MIN_NODES.get(family, 2):
                    continue
                try:
                    load_base(base_dir, family, seed, n)
                except BaseMissing as err:
                    skipped.append(f"{family} seed={seed} n={n}: {err}")
                    continue
                for directed in (True, False):
                    rows.append(write_sample(out_dir, base_dir, index, family, n,
                                             seed, directed, self_loop_rate))
                    index += 1
    fields = ["sample_id", "family", "chain", "nested", "directed", "n_nodes",
              "n_edges", "n_self_loops", "density", "seed"]
    with open(Path(out_dir) / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} samples to {out_dir} (see manifest.csv)")
    if skipped:
        print(f"Skipped {len(skipped)} (base file missing or too small), for example:")
        for line in skipped[:5]:
            print("  ", line)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="base", help="folder written by GenerateBase.java")
    p.add_argument("--out", default="samples")
    p.add_argument("--selftest", action="store_true", help="check the design rules")
    p.add_argument("--pilot", action="store_true", help="small sanity set")
    p.add_argument("--grid", action="store_true", help="full families x sizes grid")
    p.add_argument("--sizes", type=int, nargs="+", default=DEFAULT_SIZES)
    p.add_argument("--seeds", type=int, default=3, help="seeds per cell (grid mode)")
    p.add_argument("--no-caps", action="store_true",
                   help="ignore per-family max sizes (complete/dense get huge)")
    p.add_argument("--self-loop-rate", type=float, default=0.0,
                   help="probability that a node gets a self-loop (default 0)")
    p.add_argument("--family", choices=list(FAMILIES), default="tree")
    p.add_argument("--nodes", type=int, default=10)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--directed", action="store_true")
    p.add_argument("--index", type=int, default=1)
    a = p.parse_args()

    if a.selftest:
        raise SystemExit(1 if selftest(a.base) else 0)
    if a.pilot:
        generate_grid(a.out, a.base, list(FAMILIES), [10, 50], 1, True,
                      a.self_loop_rate)
    elif a.grid:
        generate_grid(a.out, a.base, list(FAMILIES), a.sizes, a.seeds,
                      not a.no_caps, a.self_loop_rate)
    else:
        meta = write_sample(a.out, a.base, a.index, a.family, a.nodes, a.seed,
                            a.directed, a.self_loop_rate)
        print(f"Wrote {a.out}/{meta['sample_id']}: {meta['n_nodes']} nodes, "
              f"{meta['n_edges']} edges")


if __name__ == "__main__":
    main()
