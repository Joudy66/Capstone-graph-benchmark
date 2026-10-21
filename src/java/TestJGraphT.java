import org.jgrapht.Graph;
import org.jgrapht.generate.*;
import org.jgrapht.graph.DefaultEdge;
import org.jgrapht.graph.SimpleGraph;
import org.jgrapht.util.SupplierUtil;

/** Smoke test: build one graph with each JGraphT generator and print its size. */
public class TestJGraphT {

    static void report(String name, GraphGenerator<Integer, DefaultEdge, ?> gen) {
        Graph<Integer, DefaultEdge> g = new SimpleGraph<>(
                SupplierUtil.createIntegerSupplier(), SupplierUtil.DEFAULT_EDGE_SUPPLIER, false);
        gen.generateGraph(g);
        System.out.printf("%-22s %4d nodes %5d edges%n", name, g.vertexSet().size(), g.edgeSet().size());
    }

    public static void main(String[] args) {
        long seed = 1;
        report("Linear (chain)",      new LinearGraphGenerator<>(10));
        report("Star",                new StarGraphGenerator<>(10));
        report("Ring (cycle)",        new RingGraphGenerator<>(10));
        report("Wheel",               new WheelGraphGenerator<>(10));
        report("Grid 3x4",            new GridGraphGenerator<>(3, 4));
        report("Complete",            new CompleteGraphGenerator<>(10));
        report("Complete bipartite",  new CompleteBipartiteGraphGenerator<>(5, 5));
        report("G(n,M) random",       new GnmRandomGraphGenerator<>(10, 15, seed));
        report("G(n,p) random",       new GnpRandomGraphGenerator<>(10, 0.3, seed));
        report("Barabasi-Albert",     new BarabasiAlbertGraphGenerator<>(2, 2, 10, seed));
        report("Watts-Strogatz",      new WattsStrogatzGraphGenerator<>(10, 4, 0.1, seed));
        report("Hypercube (dim 3)",   new HyperCubeGraphGenerator<>(3));
        System.out.println("JGraphT works.");
    }
}
