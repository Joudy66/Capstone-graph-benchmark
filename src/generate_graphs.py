"""
Benchmark generator (v4): seeded graph generator with exact ground truth.

Two design rules make the benchmark a controlled experiment:

1. GROWTH CHAINS. For a given (family, seed), the graph with 30 nodes is
   exactly the graph with 20 nodes plus 10 new nodes and their edges (same
   labels, same orientation of every shared edge). So when the size grows,
   the ONLY thing that changes is the extra nodes. This holds for the NESTED
   families (chain, star, tree, grid, bipartite, complete, sparse, dense,
   scale_free). Cycle, wheel and small_world cannot be nested (a bigger cycle
   is not a smaller cycle plus nodes), so they are built independently at
   each size; meta.json says which case applies ("nested": true/false).

2. SAME GRAPH, DIRECTED OR NOT. The directed and undirected variants of a
   sample are identical files except for the "directed" flag. Only the
   arrows differ in the picture.

Families follow the JGraphT generator catalogue (re-implemented with Python
and NetworkX, so everything stays open source).

Output per sample:
    sample_XXXXXX/
        graph.json     ground truth (schema below)
        graph.cypher   ground-truth Cypher, with sample_id on every node/edge
        meta.json      seed, family, parameters, statistics, index_to_id
(the renderer will add image_*.png and its own metadata)
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
- Node ids are "n1".."nN", shuffled per graph (numbering never leaks
  structure; ids stay short at every size). meta.json -> index_to_id gives
  the creation order, which is how nodes are paired across sizes.
- Node and edge labels come from small fixed vocabularies, assigned randomly
  but stably: a node or edge keeps its label in every larger graph.
- At most one edge per node pair; the graph is connected.
- Self-loops are OFF by default; --self-loop-rate p gives every node a loop
  with probability p (the loops are extra: the rest of the graph is unchanged).
- Undirected graphs are stored once in arbitrary direction (Cypher cannot
  store undirected edges); the evaluation must ignore direction for them.
- Natural direction (earlier node -> later node, or around the cycle/wheel)
  for chain, star, tree, grid, cycle, wheel. Random orientation otherwise.
- Every node and edge carries sample_id in Neo4j.

Requires: networkx (pip install networkx).

Usage
-----
    python generate_graphs.py --selftest                      # check the rules
    python generate_graphs.py --out samples --pilot
    python generate_graphs.py --out samples --grid
    python generate_graphs.py --out samples --grid --sizes 10 50 200 --seeds 5
    python generate_graphs.py --out samples_loops --grid --self-loop-rate 0.1
    python generate_graphs.py --out samples --family grid --nodes 100 --seed 1 --directed
"""

import argparse
import csv
import json
import random
from pathlib import Path

import networkx as nx

NODE_LABELS = ["Person", "City", "Company", "Product", "Event"]
EDGE_LABELS = ["KNOWS", "LIVES_IN", "WORKS_AT", "OWNS", "LOCATED_IN"]

# family -> (JGraphT generator it mirrors, default max nodes in the grid)
# Caps only protect the DEFAULT grid from n^2 blow-ups; --no-caps removes them.
FAMILIES = {
    "chain":       ("LinearGraphGenerator", 500),
    "star":        ("StarGraphGenerator", 500),
    "cycle":       ("RingGraphGenerator", 500),
    "wheel":       ("WheelGraphGenerator", 200),
    "tree":        ("(no direct match) random attachment tree", 500),
    "grid":        ("GridGraphGenerator", 500),
    "bipartite":   ("CompleteBipartiteGraphGenerator", 60),
    "complete":    ("CompleteGraphGenerator", 40),
    "sparse":      ("GnmRandomGraphGenerator-like, ~1.5 edges per node", 500),
    "dense":       ("GnpRandomGraphGenerator-like, each pair with p=0.5", 100),
    "scale_free":  ("BarabasiAlbertGraphGenerator-like (2 links per new node)", 500),
    "small_world": ("WattsStrogatzGraphGenerator", 500),
}
NESTED = {"chain", "star", "tree", "grid", "bipartite", "complete",
          "sparse", "dense", "scale_free"}
NATURAL_DIRECTION = {"chain", "star", "tree", "grid", "cycle", "wheel"}
MIN_NODES = {"cycle": 3, "wheel": 4, "grid": 4, "small_world": 5}
DEFAULT_SIZES = [5, 10, 15, 20, 30, 40, 50, 75, 100, 150, 200, 300, 500]
SPARSE_EXTRA_EDGE_PROB = 0.5   # tree edge + 0.5 extra edge per node = ~1.5 per node
DENSE_PAIR_PROB = 0.5          # each possible pair linked with this probability


def _rng(*parts):
    """Deterministic random generator keyed by a tuple (independent of graph size)."""
    return random.Random("|".join(str(p) for p in parts))


# --------------------------------------------------------------------------
# Structure builders: lists of (u, v) on nodes 0..n-1
# --------------------------------------------------------------------------
def _grid_positions(n):
    """Cells in 'shells' so that every prefix is a connected, near-square block."""
    pos, k = [(0, 0)], 1
    while len(pos) < n:
        pos += [(r, k) for r in range(k + 1)] + [(k, c) for c in range(k)]
        k += 1
    return pos[:n]


def nested_edges(family, seed, n):
    """Edges (earlier, later). Node i's links depend only on i and the seed,
    never on n, so the graph for n nodes is a prefix of the graph for more."""
    edges, deg = [], [0] * n
    if family == "grid":
        pos = _grid_positions(n)
        where = {p: i for i, p in enumerate(pos)}
    for i in range(1, n):
        r = _rng(seed, family, "struct", i)
        if family == "chain":
            js = [i - 1]
        elif family == "star":
            js = [0]
        elif family == "tree":
            js = [r.randrange(i)]
        elif family == "complete":
            js = list(range(i))
        elif family == "bipartite":          # parts = even / odd creation index
            js = [j for j in range(i) if j % 2 != i % 2]
        elif family == "grid":
            row, col = pos[i]
            nb = [(row - 1, col), (row, col - 1), (row + 1, col), (row, col + 1)]
            js = sorted(where[p] for p in nb if p in where and where[p] < i)
        elif family == "sparse":
            parent = r.randrange(i)
            js = [parent]
            if i >= 2 and r.random() < SPARSE_EXTRA_EDGE_PROB:
                extra = r.randrange(i)
                while extra == parent:
                    extra = r.randrange(i)
                js.append(extra)
        elif family == "dense":
            parent = r.randrange(i)          # guaranteed link keeps it connected
            js = [parent] + [j for j in range(i)
                             if j != parent and r.random() < DENSE_PAIR_PROB]
        elif family == "scale_free":         # preferential attachment, 2 links
            js = []
            while len(js) < min(2, i):
                j = r.choices(range(i), weights=[deg[x] + 1 for x in range(i)])[0]
                if j not in js:
                    js.append(j)
        else:
            raise ValueError(family)
        for j in js:
            edges.append((j, i))
            deg[j] += 1
            deg[i] += 1
    return edges


def independent_edges(family, seed, n):
    if family == "cycle":
        return [(i, (i + 1) % n) for i in range(n)]
    if family == "wheel":                    # hub 0 + rim 1..n-1
        rim = n - 1
        return ([(0, i) for i in range(1, n)]
                + [(i, i % rim + 1) for i in range(1, n)])
    if family == "small_world":
        g = nx.connected_watts_strogatz_graph(
            n, 4 if n >= 6 else 2, 0.1, tries=200,
            seed=_rng(seed, family, "sw", n).randrange(2**31))
        return list(g.edges())
    raise ValueError(family)


# --------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------
def generate_graph(family, n_nodes, seed, directed=True, self_loop_rate=0.0):
    """Returns (graph, index_to_id). index_to_id[i] is the id of creation index i."""
    if n_nodes < MIN_NODES.get(family, 2):
        raise ValueError(f"{family} needs at least {MIN_NODES.get(family, 2)} nodes")
    n = n_nodes
    edges = (nested_edges(family, seed, n) if family in NESTED
             else independent_edges(family, seed, n))

    # orientation, decided per edge (so it is stable across sizes and
    # identical in the directed and undirected variants)
    oriented = []
    for u, v in edges:
        a, b = min(u, v), max(u, v)
        if family in NATURAL_DIRECTION:
            oriented.append((u, v))
        else:
            flip = _rng(seed, family, "dir", a, b).random() < 0.5
            oriented.append((b, a) if flip else (a, b))

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
# Self-test of the two design rules
# --------------------------------------------------------------------------
def _by_index(graph, index_to_id):
    inv = {v: i for i, v in enumerate(index_to_id)}
    nodes = {inv[n["id"]]: n["label"] for n in graph["nodes"]}
    edges = {(inv[e["source"]], inv[e["target"]], e["label"]) for e in graph["edges"]}
    return nodes, edges


def selftest(seeds=(1, 2, 3), sizes=(5, 10, 15, 20, 30, 40), loop_rate=0.2):
    """Checks that (1) smaller graphs sit inside bigger ones, (2) directed and
    undirected variants are the same graph. Returns the number of failures."""
    fails = 0
    for family in FAMILIES:
        for seed in seeds:
            ok_nested = True
            for rate in (0.0, loop_rate):
                prev = None
                for n in sizes:
                    if n < MIN_NODES.get(family, 2):
                        continue
                    gd, ids = generate_graph(family, n, seed, True, rate)
                    gu, _ = generate_graph(family, n, seed, False, rate)
                    if gd["nodes"] != gu["nodes"] or gd["edges"] != gu["edges"]:
                        print(f"FAIL pair {family} seed={seed} n={n}")
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
    print("selftest:", "all checks passed" if not fails else f"{fails} FAILURES")
    return fails


# --------------------------------------------------------------------------
# Writing samples
# --------------------------------------------------------------------------
def write_sample(out_dir, index, family, n_nodes, seed, directed, self_loop_rate=0.0):
    graph, index_to_id = generate_graph(family, n_nodes, seed, directed, self_loop_rate)
    sample_id = f"sample_{index:06d}"
    folder = Path(out_dir) / sample_id
    folder.mkdir(parents=True, exist_ok=True)

    n, m = len(graph["nodes"]), len(graph["edges"])
    loops = sum(e["source"] == e["target"] for e in graph["edges"])
    meta = {
        "sample_id": sample_id,
        "family": family,
        "jgrapht_equivalent": FAMILIES[family][0],
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


def generate_grid(out_dir, families, sizes, seeds, respect_caps=True, self_loop_rate=0.0):
    """families x seeds x sizes x {directed, undirected}, plus manifest.csv."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rows, index = [], 1  # sample_000001, sample_000002, ...
    for family in families:
        cap = FAMILIES[family][1]
        for seed in range(1, seeds + 1):
            for n in sizes:
                if (respect_caps and n > cap) or n < MIN_NODES.get(family, 2):
                    continue
                for directed in (True, False):
                    rows.append(write_sample(out_dir, index, family, n, seed,
                                             directed, self_loop_rate))
                    index += 1
    fields = ["sample_id", "family", "chain", "nested", "directed", "n_nodes",
              "n_edges", "n_self_loops", "density", "seed"]
    with open(Path(out_dir) / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} samples to {out_dir} (see manifest.csv)")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="samples")
    p.add_argument("--selftest", action="store_true", help="check nesting and pairs")
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
        raise SystemExit(1 if selftest() else 0)
    if a.pilot:
        generate_grid(a.out, list(FAMILIES), [10, 50], 1, True, a.self_loop_rate)
    elif a.grid:
        generate_grid(a.out, list(FAMILIES), a.sizes, a.seeds,
                      not a.no_caps, a.self_loop_rate)
    else:
        meta = write_sample(a.out, a.index, a.family, a.nodes, a.seed,
                            a.directed, a.self_loop_rate)
        print(f"Wrote {a.out}/{meta['sample_id']}: {meta['n_nodes']} nodes, "
              f"{meta['n_edges']} edges")


if __name__ == "__main__":
    main()
