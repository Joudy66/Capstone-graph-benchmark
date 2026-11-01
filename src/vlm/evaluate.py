"""Compare the Cypher answers with the ground truth (graph.json).

  python src/vlm/evaluate.py --samples data/samples_full --out data/pilot_run

Main numbers (D12): node IDs, edges (direction ignored), node labels, edge labels.
Direction is a separate figure. Neo4j validity is NOT checked yet.
"""
import argparse, csv, json, re
from pathlib import Path

END = r"\(\s*(\w+)\s*(?::[\w:]+)?\s*(?:\{[^}]*\})?\s*\)"
NODE_RE = re.compile(r"\(\s*(\w*)\s*:\s*([A-Za-z_][\w:]*)\s*(\{[^}]*\})?\s*\)")
EDGE_RE = re.compile(END + r"\s*(<)?-\s*\[\s*\w*\s*:\s*(\w+)[^\]]*\]\s*-(>)?\s*" + END)
ID_RE = re.compile(r"id\s*:\s*['\"]([^'\"]+)['\"]")


def parse_cypher(text):
    text = re.sub(r"```\w*", "", text)
    nodes, var2id = {}, {}
    for var, labels, props in NODE_RE.findall(text):
        m = ID_RE.search(props or "")
        nid = m.group(1) if m else var
        if not nid:
            continue
        nodes[nid] = frozenset(l for l in labels.split(":") if l)
        if var:
            var2id[var] = nid
    edges = []
    for a, left, label, right, b in EDGE_RE.findall(text):
        a, b = var2id.get(a, a), var2id.get(b, b)
        if left and not right:
            a, b = b, a
        edges.append((a, b, label, bool(left or right)))
    return nodes, edges


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def evaluate(gt, text):
    g_nodes = {n["id"]: frozenset(n["label"] if isinstance(n.get("label"), list) else [n["label"]]) for n in gt["nodes"]}
    g_edges = {frozenset((e["source"], e["target"])): (e["source"], e["target"], e["label"]) for e in gt["edges"]}
    p_nodes, p_edges_list = parse_cypher(text)
    p_edges = {frozenset((a, b)): (a, b, l) for a, b, l, _ in p_edges_list}

    tp_n = len(set(g_nodes) & set(p_nodes))
    nP, nR, nF = prf(tp_n, len(p_nodes) - tp_n, len(g_nodes) - tp_n)
    both = set(g_edges) & set(p_edges)
    eP, eR, eF = prf(len(both), len(p_edges) - len(both), len(g_edges) - len(both))
    lab_n = [g_nodes[i] == p_nodes[i] for i in set(g_nodes) & set(p_nodes)]
    lab_e = [g_edges[k][2] == p_edges[k][2] for k in both]
    wrong_dir = [(g_edges[k][0], g_edges[k][1]) != (p_edges[k][0], p_edges[k][1]) for k in both] if gt.get("directed") else []
    return {
        "n_nodes": len(g_nodes), "n_edges": len(g_edges),
        "pred_nodes": len(p_nodes), "pred_edges": len(p_edges),
        "node_P": nP, "node_R": nR, "node_F1": nF,
        "edge_P": eP, "edge_R": eR, "edge_F1": eF,
        "node_label_acc": sum(lab_n) / len(lab_n) if lab_n else 0.0,
        "edge_label_acc": sum(lab_e) / len(lab_e) if lab_e else 0.0,
        "direction_error_rate": sum(wrong_dir) / len(wrong_dir) if wrong_dir else 0.0,
        "hallucinated_nodes": len(p_nodes) - tp_n, "hallucinated_edges": len(p_edges) - len(both),
        "parsed_ok": bool(p_nodes or p_edges),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--out", required=True, help="folder with the answers (one sub-folder per sample)")
    ap.add_argument("--results", help="where to save the table (default: <out>/results.csv)")
    a = ap.parse_args()
    rows = []
    for d in sorted(p for p in Path(a.out).iterdir() if (p / "answer.txt").exists()):
        gt = json.loads((Path(a.samples) / d.name / "graph.json").read_text(encoding="utf-8"))
        row = {"sample_id": d.name, **evaluate(gt, (d / "answer.txt").read_text(encoding="utf-8"))}
        raw = d / "raw_response.json"
        row["seconds"] = json.loads(raw.read_text(encoding="utf-8")).get("seconds", "") if raw.exists() else ""
        rows.append(row)
    if not rows:
        print("no answers found in", a.out); return
    keys = list(rows[0])
    res_path = Path(a.results) if a.results else Path(a.out) / "results.csv"
    res_path.parent.mkdir(parents=True, exist_ok=True)
    with open(res_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, keys); w.writeheader(); w.writerows(rows)
    cols = ["sample_id", "n_nodes", "pred_nodes", "node_F1", "edge_F1", "node_label_acc", "edge_label_acc",
            "direction_error_rate", "hallucinated_edges", "seconds"]
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join(f"{r[c]:.2f}" if isinstance(r[c], float) else str(r[c]) for c in cols))
    print("saved", res_path)


if __name__ == "__main__":
    main()
