import org.jgrapht.Graph;
import org.jgrapht.Graphs;
import org.jgrapht.generate.*;
import org.jgrapht.graph.DefaultEdge;
import org.jgrapht.graph.SimpleGraph;
import org.jgrapht.util.SupplierUtil;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.*;

/**
 * GenerateBase: builds the BASE STRUCTURE of each benchmark graph with the real
 * JGraphT generators and saves it as JSON. Python adds labels, ids, Cypher, etc.
 *
 * Decisions followed (DECISIONS.md, D3 and D13):
 *  - Connected graphs only.
 *  - NESTED families (growth chains): ONE file per (family, seed) holding the
 *    biggest graph. Its nodes are renumbered 0..n-1 in an order where EVERY
 *    prefix is connected (breadth-first order). Python keeps the first k nodes
 *    and the edges between them to get the k-node graph.
 *  - INDEPENDENT families (cycle, wheel, small_world): one file per size,
 *    no prefixes (a prefix of a cycle is not a cycle).
 *
 * File format (one JSON per file):
 *   {"family":..., "jgrapht_generator":..., "seed":1, "nested":true,
 *    "n":500, "edges":[[0,1],[0,2],...], "note":"..."}
 * Nested: edges are [earlier, later] in the new numbering.
 * Independent: edges are [source, target] as JGraphT stored them.
 * The direction of edges is decided later in Python.
 *
 * Usage (from the folder containing this file):
 *   javac -cp "LIB\*" GenerateBase.java
 *   java -cp ".;LIB\*" GenerateBase --out ..\..\data\base --seeds 1 --sizes 10 50
 *   (defaults: --out base --seeds 3, sizes 5 10 15 20 30 40 50 75 100 150 200 300 500)
 *   --no-caps removes the per-family size caps.
 */
public class GenerateBase {

    static class Fam {
        final String name, jgrapht;
        final boolean nested;
        final int cap, min;

        Fam(String name, String jgrapht, boolean nested, int cap, int min) {
            this.name = name;
            this.jgrapht = jgrapht;
            this.nested = nested;
            this.cap = cap;
            this.min = min;
        }
    }

    static final Fam[] FAMS = {
        new Fam("chain", "LinearGraphGenerator", true, 500, 2),
        new Fam("star", "StarGraphGenerator", true, 500, 2),
        new Fam("cycle", "RingGraphGenerator", false, 500, 3),
        new Fam("wheel", "WheelGraphGenerator", false, 200, 4),
        new Fam("tree", "none in JGraphT: random attachment tree written in this file", true, 500, 2),
        new Fam("grid", "GridGraphGenerator", true, 500, 4),
        new Fam("bipartite", "CompleteBipartiteGraphGenerator", true, 60, 2),
        new Fam("complete", "CompleteGraphGenerator", true, 40, 2),
        new Fam("sparse", "GnmRandomGraphGenerator", true, 500, 2),
        new Fam("dense", "GnpRandomGraphGenerator", true, 100, 2),
        new Fam("scale_free", "BarabasiAlbertGraphGenerator", true, 500, 3),
        new Fam("small_world", "WattsStrogatzGraphGenerator", false, 500, 5),
    };

    static final int[] DEFAULT_SIZES = {5, 10, 15, 20, 30, 40, 50, 75, 100, 150, 200, 300, 500};
    static final double SPARSE_EDGES_PER_NODE = 1.5;
    static final double DENSE_P = 0.5;

    // ------------------------------------------------------------------
    // Raw JGraphT graph for one family and size
    // ------------------------------------------------------------------
    static Graph<Integer, DefaultEdge> newGraph() {
        return new SimpleGraph<>(SupplierUtil.createIntegerSupplier(),
                SupplierUtil.DEFAULT_EDGE_SUPPLIER, false);
    }

    static Graph<Integer, DefaultEdge> rawGraph(String fam, int n, long seed) {
        Graph<Integer, DefaultEdge> g = newGraph();
        GraphGenerator<Integer, DefaultEdge, ?> gen;
        switch (fam) {
            case "chain":
                gen = new LinearGraphGenerator<>(n);
                break;
            case "star":
                gen = new StarGraphGenerator<>(n);
                break;
            case "cycle":
                gen = new RingGraphGenerator<>(n);
                break;
            case "wheel":
                gen = new WheelGraphGenerator<>(n);
                break;
            case "tree": {
                Random r = new Random(seed);
                g.addVertex(0);
                for (int i = 1; i < n; i++) {
                    g.addVertex(i);
                    g.addEdge(r.nextInt(i), i);
                }
                return g;
            }
            case "grid": {
                int rows = (int) Math.ceil(Math.sqrt(n));
                int cols = (int) Math.ceil(n / (double) rows);
                gen = new GridGraphGenerator<>(rows, cols);
                break;
            }
            case "bipartite":
                gen = new CompleteBipartiteGraphGenerator<>((n + 1) / 2, n / 2);
                break;
            case "complete":
                gen = new CompleteGraphGenerator<>(n);
                break;
            case "sparse": {
                int m = (int) Math.round(SPARSE_EDGES_PER_NODE * n);
                m = Math.min(m, n * (n - 1) / 2);
                gen = new GnmRandomGraphGenerator<>(n, m, seed);
                break;
            }
            case "dense":
                gen = new GnpRandomGraphGenerator<>(n, DENSE_P, seed);
                break;
            case "scale_free":
                gen = new BarabasiAlbertGraphGenerator<>(2, 2, n, seed);
                break;
            case "small_world":
                gen = new WattsStrogatzGraphGenerator<>(n, n >= 6 ? 4 : 2, 0.1, seed);
                break;
            default:
                throw new IllegalArgumentException(fam);
        }
        gen.generateGraph(g);
        return g;
    }

    // ------------------------------------------------------------------
    // Orders in which EVERY prefix is a connected graph
    // ------------------------------------------------------------------
    static List<Integer> bfs(Graph<Integer, DefaultEdge> g, Integer start, Set<Integer> seen) {
        List<Integer> order = new ArrayList<>();
        Deque<Integer> queue = new ArrayDeque<>();
        queue.add(start);
        seen.add(start);
        while (!queue.isEmpty()) {
            Integer v = queue.poll();
            order.add(v);
            List<Integer> next = new ArrayList<>();
            for (DefaultEdge e : g.edgesOf(v)) {
                Integer u = Graphs.getOppositeVertex(g, e, v);
                if (!seen.contains(u)) next.add(u);
            }
            Collections.sort(next);
            for (Integer u : next) {
                if (seen.add(u)) queue.add(u);
            }
        }
        return order;
    }

    /** Largest connected component, in breadth-first order. */
    static List<Integer> giantOrder(Graph<Integer, DefaultEdge> g) {
        Set<Integer> seen = new HashSet<>();
        List<Integer> best = new ArrayList<>();
        for (Integer v : g.vertexSet()) {
            if (!seen.contains(v)) {
                List<Integer> comp = bfs(g, v, seen);
                if (comp.size() > best.size()) best = comp;
            }
        }
        return best;
    }

    /** Complete bipartite: alternate the two sides so every prefix stays balanced. */
    static List<Integer> bipartiteOrder(Graph<Integer, DefaultEdge> g) {
        Integer start = g.vertexSet().iterator().next();
        Map<Integer, Integer> depth = new HashMap<>();
        Deque<Integer> queue = new ArrayDeque<>();
        queue.add(start);
        depth.put(start, 0);
        while (!queue.isEmpty()) {
            Integer v = queue.poll();
            for (DefaultEdge e : g.edgesOf(v)) {
                Integer u = Graphs.getOppositeVertex(g, e, v);
                if (!depth.containsKey(u)) {
                    depth.put(u, depth.get(v) + 1);
                    queue.add(u);
                }
            }
        }
        List<Integer> a = new ArrayList<>(), b = new ArrayList<>();
        for (Integer v : g.vertexSet()) {
            if (depth.get(v) % 2 == 0) a.add(v);
            else b.add(v);
        }
        Collections.sort(a);
        Collections.sort(b);
        List<Integer> order = new ArrayList<>();
        for (int i = 0; i < Math.max(a.size(), b.size()); i++) {
            if (i < a.size()) order.add(a.get(i));
            if (i < b.size()) order.add(b.get(i));
        }
        return order;
    }

    static Integer maxDegreeVertex(Graph<Integer, DefaultEdge> g) {
        Integer best = null;
        for (Integer v : g.vertexSet()) {
            if (best == null || g.degreeOf(v) > g.degreeOf(best)) best = v;
        }
        return best;
    }

    // ------------------------------------------------------------------
    // Output
    // ------------------------------------------------------------------
    static boolean connected(int n, List<int[]> edges) {
        int[] parent = new int[n];
        for (int i = 0; i < n; i++) parent[i] = i;
        int comps = n;
        for (int[] e : edges) {
            int a = find(parent, e[0]), b = find(parent, e[1]);
            if (a != b) {
                parent[a] = b;
                comps--;
            }
        }
        return comps == 1;
    }

    static int find(int[] p, int x) {
        while (p[x] != x) {
            p[x] = p[p[x]];
            x = p[x];
        }
        return x;
    }

    static void write(String outDir, String file, Fam f, int seed, int n,
                      List<int[]> edges, String note) throws IOException {
        if (!connected(n, edges)) {
            throw new IllegalStateException("Graph not connected: " + file);
        }
        StringBuilder sb = new StringBuilder();
        sb.append("{\"family\":\"").append(f.name).append("\",");
        sb.append("\"jgrapht_generator\":\"").append(f.jgrapht).append("\",");
        sb.append("\"seed\":").append(seed).append(",");
        sb.append("\"nested\":").append(f.nested).append(",");
        sb.append("\"n\":").append(n).append(",");
        sb.append("\"note\":\"").append(note).append("\",");
        sb.append("\"edges\":[");
        for (int i = 0; i < edges.size(); i++) {
            if (i > 0) sb.append(",");
            sb.append("[").append(edges.get(i)[0]).append(",").append(edges.get(i)[1]).append("]");
        }
        sb.append("]}\n");
        Files.write(Paths.get(outDir, file), sb.toString().getBytes(StandardCharsets.UTF_8));
        System.out.printf("%-12s seed=%d %-11s n=%-4d edges=%d%n",
                f.name, seed, f.nested ? "nested" : "independent", n, edges.size());
    }

    // ------------------------------------------------------------------
    // One nested file: the biggest graph, renumbered in prefix-connected order
    // ------------------------------------------------------------------
    static void buildNested(String outDir, Fam f, int seed, long s, int maxN) throws IOException {
        Graph<Integer, DefaultEdge> g;
        List<Integer> order;
        String note;
        if (f.name.equals("sparse") || f.name.equals("dense")) {
            // random graphs may be in pieces: keep the largest piece, grow the
            // raw graph until that piece has at least maxN nodes
            int rawN = maxN;
            while (true) {
                g = rawGraph(f.name, rawN, s);
                order = giantOrder(g);
                if (order.size() >= maxN) break;
                rawN += Math.max(2, rawN / 10);
            }
            note = "largest connected piece of a graph with " + rawN
                    + " nodes, first " + maxN + " nodes in breadth-first order";
        } else {
            g = rawGraph(f.name, maxN, s);
            if (f.name.equals("bipartite")) {
                order = bipartiteOrder(g);
                note = "sides alternated, first " + maxN + " nodes";
            } else if (f.name.equals("star")) {
                order = bfs(g, maxDegreeVertex(g), new HashSet<>());
                note = "breadth-first from the hub";
            } else {
                order = bfs(g, g.vertexSet().iterator().next(), new HashSet<>());
                note = "breadth-first from the first vertex";
            }
        }
        int keep = maxN;
        Map<Integer, Integer> idx = new HashMap<>();
        for (int i = 0; i < keep; i++) idx.put(order.get(i), i);
        List<int[]> edges = new ArrayList<>();
        for (DefaultEdge e : g.edgeSet()) {
            Integer a = idx.get(g.getEdgeSource(e)), b = idx.get(g.getEdgeTarget(e));
            if (a != null && b != null) edges.add(new int[]{Math.min(a, b), Math.max(a, b)});
        }
        edges.sort((x, y) -> x[0] != y[0] ? Integer.compare(x[0], y[0]) : Integer.compare(x[1], y[1]));
        write(outDir, f.name + "_seed" + seed + ".json", f, seed, keep, edges, note);
    }

    // ------------------------------------------------------------------
    // One independent file: a graph of exactly this size
    // ------------------------------------------------------------------
    static void buildIndependent(String outDir, Fam f, int seed, long s, int n) throws IOException {
        Graph<Integer, DefaultEdge> g = null;
        int attempts = 0;
        while (true) {
            g = rawGraph(f.name, n, s + 1000003L * attempts);
            List<Integer> vs = new ArrayList<>(g.vertexSet());
            Map<Integer, Integer> idx = new HashMap<>();
            for (int i = 0; i < vs.size(); i++) idx.put(vs.get(i), i);
            List<int[]> edges = new ArrayList<>();
            for (DefaultEdge e : g.edgeSet()) {
                edges.add(new int[]{idx.get(g.getEdgeSource(e)), idx.get(g.getEdgeTarget(e))});
            }
            if (vs.size() == n && connected(n, edges)) {
                String note = attempts == 0 ? "as generated"
                        : "reseeded " + attempts + " time(s) to get a connected graph";
                write(outDir, f.name + "_seed" + seed + "_n" + n + ".json", f, seed, n, edges, note);
                return;
            }
            if (++attempts > 200) {
                throw new IllegalStateException("No connected graph after 200 tries: " + f.name + " n=" + n);
            }
        }
    }

    // ------------------------------------------------------------------
    public static void main(String[] args) throws IOException {
        String out = "base";
        int seeds = 3;
        int[] sizes = DEFAULT_SIZES;
        boolean caps = true;
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--out":
                    out = args[++i];
                    break;
                case "--seeds":
                    seeds = Integer.parseInt(args[++i]);
                    break;
                case "--no-caps":
                    caps = false;
                    break;
                case "--sizes": {
                    List<Integer> list = new ArrayList<>();
                    while (i + 1 < args.length && !args[i + 1].startsWith("--")) {
                        list.add(Integer.parseInt(args[++i]));
                    }
                    sizes = list.stream().mapToInt(Integer::intValue).toArray();
                    break;
                }
                default:
                    throw new IllegalArgumentException("Unknown option " + args[i]);
            }
        }
        Files.createDirectories(Paths.get(out));
        int files = 0;
        for (int fi = 0; fi < FAMS.length; fi++) {
            Fam f = FAMS[fi];
            for (int seed = 1; seed <= seeds; seed++) {
                long s = seed * 7919L + fi * 104729L;
                if (f.nested) {
                    int maxN = 0;
                    for (int size : sizes) {
                        if ((!caps || size <= f.cap) && size >= f.min) maxN = Math.max(maxN, size);
                    }
                    if (maxN == 0) continue;
                    buildNested(out, f, seed, s, maxN);
                    files++;
                } else {
                    for (int size : sizes) {
                        if ((caps && size > f.cap) || size < f.min) continue;
                        buildIndependent(out, f, seed, s, size);
                        files++;
                    }
                }
            }
        }
        System.out.println("\nWrote " + files + " files to " + out);
    }
}
