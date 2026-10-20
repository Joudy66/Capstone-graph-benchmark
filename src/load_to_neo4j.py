"""
Load generated samples into ONE Neo4j Community database, read them back
("API pull") and verify that what comes back equals graph.json exactly.

Neo4j Community has a single user database, so every node and edge carries a
sample_id property and graphs never mix.

Setup:   pip install neo4j
Usage:   python load_to_neo4j.py --samples samples            # load + verify all
         python load_to_neo4j.py --samples samples --reset    # wipe DB first
         python load_to_neo4j.py --samples samples --only sample_000001

Connection (defaults match the docker command from the chat; override with
environment variables NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD).

The function pull_graph() is what the renderer will use: it reads one graph
from Neo4j and returns the same structure as graph.json.
"""

import argparse
import json
import os
from pathlib import Path

from neo4j import GraphDatabase

from generate_graphs import NODE_LABELS

URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")


def setup_indexes(session):
    for label in NODE_LABELS:
        session.run(f"CREATE INDEX sample_id_{label.lower()} IF NOT EXISTS "
                    f"FOR (n:{label}) ON (n.sample_id)")


def is_loaded(session, sample_id):
    q = "MATCH (n {sample_id: $s}) RETURN count(n) AS c"
    return session.run(q, s=sample_id).single()["c"] > 0


def load_sample(session, folder):
    """Run graph.cypher for one sample. Returns 'loaded' or 'skipped'."""
    if is_loaded(session, folder.name):
        return "skipped"
    session.run((folder / "graph.cypher").read_text(encoding="utf-8")).consume()
    return "loaded"


def pull_graph(session, sample_id, directed=True):
    """Read one graph back from Neo4j, in the graph.json structure."""
    nodes = session.run(
        "MATCH (n {sample_id: $s}) RETURN n.id AS id, labels(n)[0] AS label",
        s=sample_id)
    edges = session.run(
        "MATCH (a {sample_id: $s})-[r]->(b) "
        "RETURN a.id AS source, b.id AS target, type(r) AS label", s=sample_id)
    return {
        "directed": directed,
        "nodes": sorted(({"id": r["id"], "label": r["label"]} for r in nodes),
                        key=lambda d: int(d["id"][1:])),
        "edges": sorted(({"source": r["source"], "target": r["target"],
                          "label": r["label"]} for r in edges),
                        key=lambda e: (int(e["source"][1:]), int(e["target"][1:]))),
    }


def verify(session, folder):
    """True if the graph in Neo4j equals graph.json (nodes, edges, labels, direction)."""
    truth = json.loads((folder / "graph.json").read_text(encoding="utf-8"))
    back = pull_graph(session, folder.name, truth["directed"])
    return truth == back


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--samples", default="samples")
    p.add_argument("--reset", action="store_true", help="delete everything first")
    p.add_argument("--only", help="load a single sample folder name")
    a = p.parse_args()

    folders = sorted(f for f in Path(a.samples).glob("sample_*") if f.is_dir())
    if a.only:
        folders = [f for f in folders if f.name == a.only]

    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    bad = []
    with driver.session() as s:
        if a.reset:
            s.run("MATCH (n) DETACH DELETE n").consume()
        setup_indexes(s)
        for i, folder in enumerate(folders, 1):
            status = load_sample(s, folder)
            ok = verify(s, folder)
            if not ok:
                bad.append(folder.name)
            print(f"[{i}/{len(folders)}] {folder.name}: {status}, "
                  f"round-trip {'OK' if ok else 'MISMATCH'}")
    driver.close()
    print(f"\n{len(folders) - len(bad)}/{len(folders)} samples verified.")
    if bad:
        print("Mismatches:", ", ".join(bad))


if __name__ == "__main__":
    main()
