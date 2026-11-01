# Design decisions log

Every methodology decision, with the reason and the alternatives considered.
This file becomes the methodology section of the paper.
Last full update: 1 Nov 2026 (pipeline renderer, DVC stages and first local Qwen pilot; earlier update: 26 Oct, after the meeting with the professor of 23 Oct). Status: **decided**, **decided, details open**, **postponed**, or **open**.

---

## Decided

### D1. Generate the graphs instead of collecting web images
- **Why:** exact ground truth, controlled variables, measurable overlaps, clean licensing.
- **Alternative:** web images (hand annotation, licence checks). A small real set is planned instead (see D10).

### D2. Fixed label vocabularies, assigned randomly
- 5 node labels (Person, City, Company, Product, Event), 5 edge labels (KNOWS, LIVES_IN, WORKS_AT, OWNS, LOCATED_IN).
- **Why:** simple colour coding and label scoring; random assignment tests reading the image, not guessing from meaning.
- Labels depend only on the node index (or the edge's two node indices) and the seed, so a node or edge keeps its label in every bigger graph.
- **Changed 23-24 Oct, multi-label nodes (decided):** the professor's colour example (yellow = Firefighter, blue = Officer, green = both) shows a node that carries two labels.
  - **New node label Employee.** It appears only together with Person (a Person who is also an Employee), never alone.
  - **Only two allowed pairs:** Person + Employee, and City + Event (the event is in the city). A node never has more than two labels. Not all pairs are included, because this is an experiment.
  - **Switch** (like the self-loops, D5), for example `--multi-label-rate`: **off** for the base set (the current 822 samples stay valid), and **20%** of the eligible nodes (Person, City and Event nodes) in a separate multi-label set. One rate only.
  - **Assignment** is deterministic from the seed and the node index, so growth chains (D3) keep working.
  - **Cypher:** real multi-label nodes, for example `(:Person:Employee {id: 3})`. The label check (D12, check 3) compares the full set of labels of a node.
  - **Caveat to report:** logical pairs may let a model guess the second label from context (for example a WORKS_AT edge). D2's random assignment is kept for single labels.
  - **Code to change:** generator v5 (one label per node today), the loader, and the evaluation code (compare label sets).
  - **Alternatives:** keep one label per node; one combined label such as `PersonEmployee` (hides the two labels, not how a real database is modelled); all ten pairs (too many colours).

### D3. Growth chains (nested graphs)
- For a given family and seed, the 30-node graph contains the 20-node graph plus new nodes (same labels, same edges). Only the added nodes change between sizes.
- **How (decided 21 Oct):** JGraphT builds the biggest graph for each (family, seed). The Java program renumbers its nodes in breadth-first order, so every prefix is connected. Python keeps the first k nodes and the edges between them.
  - Star: breadth-first from the hub. Bipartite: the two sides are alternated so every prefix stays balanced.
  - Sparse and dense: these random graphs can come in pieces, so the largest connected piece is kept (the raw graph is grown until that piece is big enough).
- Cycle, wheel and small-world cannot be nested and are generated independently at each size (`"nested": false` in `meta.json`).
- **Alternative:** generate each size separately (no nesting; a change in accuracy would mix "bigger" with "a different graph").
- **Known side effect:** see D19.

### D4. Directed and undirected variants are the same graph
- **Why:** isolates the effect of drawing arrows.
- Natural direction for chain, star, tree, grid (earlier to later node), cycle (around the cycle) and wheel (hub to rim, rim around). Random direction, fixed per edge, for the other families.
- **Drawing (23 Oct):** direction stays drawn with arrows for now (see D22).

### D5. Self-loops are a switch, off by default
- **Why:** loops are a hard visual case; a separate switch lets their effect be measured alone.

### D6. Sizes from 5 to 500 nodes, no hard cap except on n^2 families
- Caps only on complete (40), bipartite (60), dense (100), wheel (200); `--no-caps` removes them.
- **Why:** the goal is to find where models fail.
- **Keep in mind:** very large graphs can fail from the output length limit, not from vision. The failure taxonomy must separate the two.
- **Seen in the first pilot (1 Nov):** a 2B model on the laptop failed in two ways that are not vision failures: it spent the whole token budget on reasoning (D27), or it repeated lines in a loop and never reached the edges. The taxonomy needs a category "ran out of tokens / repetition loop". The evaluation must record the stop reason (`done_reason` in `raw_response.json`) so these runs can be separated; `evaluate.py` does not do this yet.

### D7. One factor at a time, results as curves with uncertainty, plus a small joint grid
- Change one factor at a time (nodes, edges, resolution, visual features). Report accuracy as a curve with a confidence interval over seeds. Breaking thresholds (first size below the 0.9 and 0.5 cut-offs) are read from the curve with their uncertainty.
- **Joint grid:** nodes x resolution (about 4 sizes x 3 resolutions) on two families (for example sparse and tree). Space per node is about resolution^2 / nodes, so this separates perception failures (nodes too small) from counting and output-length failures. Final go-ahead after the pilot.
- **Alternatives considered:** full factorial grid, random parameters plus regression, adaptive search.

### D9. Readability: keep every image, add a "readable" flag
- Compute readability measures per image (minimum node diameter in pixels, edges hidden under nodes), store them next to the render output (`render_info.json`, see D28). Thresholds are computed on readable images only; the unreadable region is shown separately as "beyond readability".
- Crossing edges are readable (a difficulty); hidden nodes or edges are not.
- **Details open:** numeric rules. Plan: read about 20 hard images by hand to place the line.
- **Alternatives:** filter out unreadable images; keep everything without a flag.
- **Note (23 Oct):** the D3 renderer (D20) gives exact node positions and sizes, which makes these measures and the overlap counter easier to compute.

### D10. Visual feature conditions, style robustness, small real-image set
- **Professor's request:** test whether putting labels on nodes and edges changes results, and whether using colour to mimic direction does. These are the visual-feature conditions (same graph drawn with the feature on and off).
- **Style robustness (light):** re-draw a subset with a few layouts and palettes.
- **Real images:** a small set of 10-30, hand-annotated into the same `graph.json` format (node ids and labels, edge source/target/label, direction). Images with unclear ids or labels are flagged.
- **Edge labels (decided 23 Oct):** shown only as colour, never as text (see D21).
- **Details open:** exact list of feature conditions, definition of "colour to mimic direction" (for example edges in the source node's colour instead of arrowheads), sources and licences of the real images (Wikimedia Commons, CC-BY papers, Neo4j screenshots, own hand-drawn graphs).

### D12. Metrics and breaking point
- **Main curve:** edge F1 with direction ignored.
- **Shown alongside:** direction error rate, exact reconstruction rate, invalid-output rate.
- **Unrunnable Cypher:** F1 on valid outputs only, plus the invalid-output rate on the same chart (their product is the score-0 version).
- **Cut-offs:** 0.9 for reliable and 0.5 for broken, to confirm with the professor.
- **Added 23 Oct, the four checks used to compare the VLM output with the ground truth Cypher:** (1) node IDs, (2) edges (source and target node IDs), (3) node labels, (4) edge labels. The professor explained these as the four rules of the check.
- **Decided 23 Oct:** direction is a separate figure (the direction error rate above), not part of check (2). A reversed edge counts as found, with a wrong direction.
- **Implementation (1 Nov, `src/vlm/evaluate.py`, first version):** nodes are matched by ID; edges by their two node IDs, direction ignored (no parallel edges assumed); node label accuracy is computed over matched nodes (full label set) and edge label accuracy over matched edges; direction error rate over matched edges of directed graphs; hallucinated nodes and edges are counted. The answer text is read with simple patterns (CREATE statements with an `id` property). It is not yet run in Neo4j, so Cypher validity (invalid-output rate) is not measured yet.
- **Warning:** with sequential IDs (n1, n2, n3, ...) node F1 can be high just from counting upward. Label accuracy and the edge scores say more about whether the image was read.

### D13. JGraphT: use the real library, through Java
- The professor's requirement is to use JGraphT and its graph types. His pipeline sketch: JGraphT, then JSON (graph), then database. This part is **done**.
- The Python bindings (`pip install jgrapht`) have prebuilt packages only up to Python 3.8 and failed to build on Python 3.12, so they are not used.
- **Route 2 (implemented 21 Oct):** `GenerateBase.java` (JDK 21, Eclipse Temurin, JGraphT 1.5.3 jars) builds the base structure of each graph and saves it as JSON. `generate_graphs.py` (v5) reads these files and does the rest (labels, ids, directions, Cypher, `meta.json`). Neo4j and evaluation follow in Python. **Rendering is no longer done in Python/Graphviz (see D20).**
- **Growth chains:** connected prefixes of the biggest graph (see D3).
- **Graphs in several pieces:** not allowed for now (see D18).
- **Families:** the current 12 first (chain, star, cycle, wheel, tree, grid, bipartite, complete, sparse, dense, scale_free, small_world). Extra JGraphT families (hypercube, generalized Petersen, windmill, planted partition, random regular, Kleinberg small-world, Barabasi-Albert forest) may be added later; the code is written so adding one is easy.
- **Tree:** JGraphT has no random-tree generator that was used here, so the tree family is a random attachment tree written in `GenerateBase.java` (same idea as v4). To confirm with the professor.
- **Seeds:** the JGraphT seed is derived from the sample's seed number and the family.
- **Alternative:** Python-only re-implementation with NetworkX (v4), kept in Git history.

### D14. Models: one family at several sizes
- Option B for now (may change): the Qwen family. Candidate: Qwen3-VL (2B, 4B, 8B dense; 32B probably only on the INSA cluster), reported by third-party pages as Apache-2.0.
- **Licence check (1 Nov):** the official model card `Qwen/Qwen3-VL-2B-Instruct` on Hugging Face lists Apache-2.0. The other sizes and the Thinking cards are still to check.
- **Details open:** exact sizes beyond the 2B test; check for newer Qwen releases (third-party pages mention newer Qwen versions with vision).
- **Local test (31 Oct to 1 Nov):** Qwen3-VL 2B through Ollama on the laptop. The 4B (about 3.3 GB) fits in 16 GB of RAM but was not tried (slower). See D24 and D27.
- **Alternatives:** same size across several families; a mix.
- See D24 for the local setup used to build the pipeline.

### D18. Connected graphs only (for now)
- Every graph is one connected piece; the generator checks this for every sample.
- **Why:** one object for the model to read; growth chains stay clean (a prefix of a connected graph in breadth-first order is connected).
- **Alternative:** allow graphs in several pieces (a harder case: the model must not merge pieces; nesting becomes unclear). To discuss with the professor, then possibly add as a separate condition.

### D19. Density drift in nested random families is accepted and documented
- Checked on the 822-sample set (mean over 3 seeds). Edges per node:

| Nodes | Sparse | Scale-free | Dense (density) |
|---|---|---|---|
| 10 | 0.9 | 1.5 | 0.61 |
| 50 | 1.06 | 1.3 | 0.52 |
| 200 | 1.3 | 1.7 | not generated (cap 100) |
| 500 | 1.6 | 2.0 | not generated (cap 100) |

- Small sparse graphs are almost trees; sparse only reaches about 1.5 edges per node at 500 nodes. Scale-free drifts from about 1.3 to 2.0. Dense settles near 0.5 after the smallest sizes.
- **Decision (option A):** keep sparse and scale-free nested. The drift is reported in the paper, and "bigger" for these families also means "more edges per node".
- **Alternatives:** make sparse independent per size (constant density, no growth chain); keep nested and add an independent sparse family later.

### D20. Images are drawn with D3 (JavaScript), not Graphviz (decided 23 Oct)
- **Professor's pipeline:** JSON (graph), then an API pull that turns the JSON into an image (D3 or vis.js), then the VLM, then Cypher, then compared with the database.
- **Choice:** D3 (open source, ISC licence as far as known; verify on the repository). Chosen because it gives exact control of node size and position, seeded and deterministic layouts, sharp SVG output at 512 / 1024 / 2048 px, and node coordinates for the overlap counter and the readability flags (D9). Cost: more code than vis.js.
- **Alternative:** vis.js (vis-network, Apache-2.0 / MIT as far as known): faster to get a first picture, less control over exact sizes and positions.
- **Replaces:** the earlier plan "pull from Neo4j, then draw with Graphviz" and the Graphviz rendering step in the specification (section 5). The rendering rules of the specification (fixed palette, IDs inside nodes, fixed resolutions, rendering parameters stored in `meta.json`) still apply.
- **PNG conversion (decided 31 Oct, option A):** D3 runs in Node.js and writes an SVG; `@resvg/resvg-js` (MPL-2.0) converts it to PNG, with no browser. Chosen over a headless browser (Puppeteer or Playwright: about 170 MB download, more RAM, slower; a bad fit for a laptop that overheats). The font is DejaVu Sans Bold, bundled in `src/render/fonts/` (free licence of the DejaVu fonts; check the licence text before the release, D17). d3-force is ISC (read from its package file).
- **Built (renderer v1.1, `src/render/`):** palette and encoding of D21; arrowheads in the line colour and larger than the line; 512 / 1024 / 2048 px images are the same drawing zoomed, so line width scales with image size; an unknown label stops the render with an error. Tested on made-up graphs up to 500 nodes and on the real pilot samples. At 500 nodes the image is a dense tangle with many hidden edges; this is what the readable flag (D9) is for. Output location: see D28.
- **Source of the pull (decided 23 Oct):** the renderer reads the graph JSON files directly, not Neo4j. The JSON files are the ground truth and Neo4j holds the same graphs (checked by round trip), so reading Neo4j would add a dependency without a benefit.

### D21. Visual encoding of labels (decided 23-24 Oct)
- **Text in the centre of each node:** the node ID exactly as stored (`n1`, `n2`, ...), decided 25 Oct. IDs are always visible (see D11).
  - **Why:** what the model reads is exactly what the ground truth contains, so no conversion rule is needed in the prompt.
  - **Alternative:** show only the number (`1`, `2`): cleaner and more room in small nodes, but the prompt would need the rule "write the ID as n plus the number".
- **Node colour = node label. Edge colour = edge label** (professor's example: node 1 green, node 2 orange, edge pink for the label HAS).
- **Edge labels appear only as colour, no text on the image** (decided 23 Oct).
- **Colour key (decided 24 Oct): a fixed rule in the main prompt, the same text for every graph.** No legend is drawn in the image.
  - **For:** the image stays clean and the same size, so only the graph changes; one prompt rule covers every sample.
  - **Against:** the image alone is no longer enough to read the labels, so the colours must be easy to name.
  - **Alternatives:** legend drawn in the image (takes space, harder to read at 512 px, adds a second thing that can fail; it may be tested later as an extra condition in D10, not decided); no key at all (the model guesses from colour, too hard as a main setting).
- **Palette:** clearly different basic colours (orange, white, pink, yellow, and so on), no close shades.
  - Node colours needed: 5 single labels (Person, City, Company, Product, Event) + 2 pairs (Person + Employee, City + Event) = **7**. Edge colours needed: **5**.
  - **Two-label nodes:** each of the two allowed pairs has its own fixed colour, listed in the prompt rule. The colour may look like a blend of its two labels, but must never look like a single-label colour. (Middle way between "mixed colour" and "fixed colour per pair".)
  - **Alternatives considered:** a node split into two halves; fill colour plus an outline ring for the second label; a pure computed mix (can collide with a single-label colour).
- **Working palette (proposed 24 Oct, used for the first renderer; any colour can still be changed after the first images are checked).** Nodes use light fills with a black outline and a black ID; edges use strong, dark colours so a thin line stays visible against a node.

| Node label | Colour |
|---|---|
| Person | orange `#FFA94D` |
| City | blue `#74C0FC` |
| Company | white `#FFFFFF` (thick black outline) |
| Product | yellow `#FFE066` |
| Event | pink `#FFA8D1` |
| Person + Employee | mint green `#63E6BE` |
| City + Event | purple `#B197FC` (blue + pink) |

| Edge label | Colour |
|---|---|
| KNOWS | green `#1FA34A` |
| LIVES_IN | red `#E03131` |
| WORKS_AT | blue `#1C64F2` |
| OWNS | black `#111111` |
| LOCATED_IN | brown `#8B5A2B` |

- **Edge style (decided 24 Oct):**
  - **Arrowhead has the same colour as the line**, so the whole edge reads as one coloured object. The arrowhead must be clearly visible: larger than the default size (exact size set while building the renderer and checked on sample images).
  - **Line width is scaled with the image size**, so edges take about the same share of the image at 512, 1024 and 2048 px. Only the node size changes with resolution.
  - **Alternatives:** black arrowhead (stands out, but the head can hide the line's colour); fixed width in pixels (edges become relatively thinner at 2048 px).
- **Known difficulty:** thin lines, crossings, and five line colours are hard to tell apart at 512 px. This is a difficulty the benchmark measures, not something to hide.
- **Details open:** confirm the palette after the first rendered images (white needs the dark outline on a white background). First real images were rendered 31 Oct; the confirmation of the colours is still pending.

### D22. Direction stays drawn with arrows for now (decided 23 Oct, idea postponed)
- **Professor's idea:** square node = source, circle node = destination, instead of arrows.
- **Problem found:** a node can be both. In a chain 1 to 2 to 3, node 2 is the destination of the first edge and the source of the second, so one node shape cannot be right. The rule only works when every node is purely a source or purely a destination (for example a star pointing out from the hub).
- **Decision:** keep standard arrowheads (as in the specification). The shape idea is postponed.
- **Options for later:** apply shapes only on families where it works; mark the edge ends (square at the tail, circle at the head); keep arrows as the main style and add shapes as an extra visual-feature condition (D10); ask the professor what he meant.

### D24. Local Qwen setup, only to build the pipeline (23 Oct; installed 31 Oct)
- The laptop (Dell Latitude 7430) has integrated Intel Iris Xe graphics and no dedicated GPU, so models run on the CPU. This is enough to test the pipeline on a few images, not to run sweeps.
- **Plan:** a small Qwen3-VL model (2B, then 4B if the RAM allows) installed locally, called through a local HTTP API, so the same code can later point to a server on the INSA cluster. Recommended route: Ollama. Alternative: Hugging Face Transformers (closer to the later LoRA training).
- **Training and big sweeps:** on INSA resources. Access, GPUs and job limits are still unknown (question for the professor).
- **Installed (31 Oct):** Ollama on Windows, with `qwen3-vl:2b` and `qwen3-vl:2b-instruct`. Laptop: 16 GB DDR4 RAM; CPU reported as "8" (cores or threads not confirmed). Speed on the CPU: about 11 tokens per second for the 2B model, so a 2500-token answer takes about 4 minutes; reading the image takes about 40 s. The model is called through Ollama's local HTTP address (`src/vlm/run_vlm.py`), so the same code can later point to an INSA server.
- **Still open:** whether to try the 4B locally; INSA access.

### D25. Pipeline: stages run and versioned with DVC, not Airflow (decided 26 Oct)
- **Why not Airflow (professor's suggestion):** it runs several background services (web server, scheduler, database) and made the laptop overheat. It is built for scheduled production jobs, while this work is a batch of experiments that are edited and rerun.
- **Choice:** DVC (open source, Apache-2.0 as far as known; verify on its repository). It runs on Windows, starts no background services, tracks stages and settings, and versions data (useful for the release, D17).
- **How:** `dvc.yaml` lists the stages with their input and output files; `params.yaml` holds the settings (model, prompt, resolution, palette); `dvc repro` reruns only the stages affected by an edit. The big data stays out of Git; a storage place for it is chosen later (folder, external drive, or INSA storage).
- **Limit:** DVC works at stage level. Our own scripts must also skip any image or model answer that already exists, so a sweep is never repeated (the specification asks to save every model output).
- **Stages (each reads files and writes files):** 1 generate (done), 2 render (D3, done 1 Nov), 3 splits and manifest, 4 inference (image + prompt to the raw answer, through a local HTTP address so the same code runs on the laptop and on INSA), 5 parse (raw answer to JSON or Cypher, run in Neo4j), 6 evaluate (the four checks and metrics to a results table), 7 analyse (curves, thresholds, failure taxonomy).
- **Flexibility rules:** one stage = one small command; settings live in config files, not in code; every run has its own folder with a copy of its settings.
- **Alternatives:** plain scripts with a small launcher (lightest, no tooling to learn); Snakemake (reruns only what an edit affects, works on clusters, best on Linux or WSL); Prefect or Dagster (heavier, probably the same heat problem).
- **To ask the professor:** is Airflow required, or is a lighter tool acceptable?
- **Implemented (1 Nov, first version):**
  - `dvc init`; the data folders `samples_full`, `base_full` and the pilot results are tracked with `dvc add` (one small `.dvc` file each, saved in Git). `.gitignore` now says `data/*` plus `!data/*.dvc`, so Git keeps the small files and ignores the data.
  - Pipeline in `dvc.yaml`: **render, then vlm, then evaluate**, for a list of sample IDs (`configs/pilot_ids.txt`: samples 301, 303, 307 and 309). All settings are in `params.yaml` (render resolution; model, prompt file, sampling, token cap, run name).
  - Tested: a second run does nothing; a changed setting reruns only the stages it affects; a failed model call shows the stage as failed. `run_vlm.py` reuses a saved answer only if model, settings and prompt are identical (the answer file stores them), so old answers cannot be mixed with new settings.
  - Not yet DVC stages: generate, splits, parse in Neo4j, analyse.
- **Not done yet:** a DVC remote. Today the data and its cache exist only on the laptop, so they are versioned but not backed up. Options: a folder, an external drive, or INSA storage.

### D26. Layout of the nodes in the images: option C (decided 31 Oct)
- **Choice:** D3 force-directed layout, seeded, for all main experiments. Other layouts per family (circle, grid, tree, force) only on a small subset later, as an extra condition that fits the style-robustness subset of D10.
- **Why:** one rule for every family keeps the main thresholds comparable; the subset then shows whether the layout matters.
- **Implemented (renderer v1.1):** the layout seed comes from the graph itself (node IDs plus undirected edges) and an option `--layout-seed` (default 0). The directed and undirected twins therefore get the same node positions and only the arrows differ (D4). The layout is computed in a fixed 1000 x 1000 drawing space and scaled to 512 / 1024 / 2048 px. Final positions are saved in `render_info.json` (D28).
- **Known side effect:** a bigger graph of a growth chain (D3) gets a new layout; the old nodes do not stay in place.
- **Alternatives:** one layout for everything with no subset; a layout per family for all experiments (layout and family would be mixed, so a change in accuracy could not be assigned to one cause).

### D27. Thinking or Instruct version of the model (decided 31 Oct for the pipeline test; Thinking comparison planned)
- **What happened:** in Ollama the plain `qwen3-vl:2b` tag behaved as the Thinking version: it writes reasoning before the answer, and the request `think: false` did not stop it. On 10, 20 and 30 nodes all 4096 tokens went into thinking (11,029 characters on the 10-node sample), the answer was empty and the run stopped with `done_reason: length`. The 5-node sample finished: all nodes, edges and labels correct, 1 of 4 arrows reversed. A 4096-token run took about 6 minutes.
- **Decision:** use the Instruct version (`qwen3-vl:2b-instruct`) to build and test the pipeline. Compare Thinking and Instruct later as two separate conditions (same graphs, prompt and resolution) on INSA, with a higher token cap. Report both, never mix them.
- **Why Thinking later:** the reasoning text may show where the model goes wrong when reading the graph (for the failure taxonomy and for prompt changes). Caution: it is the model's own account, not a recording of what it saw. Each suspicion must be checked against `graph.json`.
- **Cost:** Thinking needs more tokens and time. Cost per graph is already a metric (specification section 7). A failure by running out of tokens is not a failure to see (D6).
- **Alternatives:** Thinking only with a much higher token cap (too slow on the laptop); Instruct only.

### D28. Render output in its own folder (decided 1 Nov, option A)
- **Choice:** the renderer writes to `data/render/<sample_id>/`: `image_<res>.png` and `render_info.json` (renderer and palette versions, layout seed, node radius, node diameter in pixels per resolution, node positions). The sample folders (`graph.json`, `graph.cypher`, `meta.json`) are read-only input and are never changed.
- **Why:** DVC cannot track an output inside a folder it already tracks. Separate output also means the 822 samples never change when images are redrawn.
- **Consequence:** the overlap counter and readability numbers (D9) read `render_info.json`. Text elsewhere that says "stored in `meta.json`" now means `render_info.json`. Some `meta.json` files may still hold an unused `rendering` block from renderer v1.0; nothing reads it.
- **Alternatives:** one folder per resolution (files of one sample are scattered; less natural for tiling, E3); keep writing into the sample folders (blocks DVC stages).

---

## Postponed

### D11. Node matching when IDs are hidden (postponed 23 Oct)
- **For now there are no hidden IDs:** every image shows the node IDs, so nodes are matched by ID. Hidden IDs may come back later as a harder condition.
- Kept for later: exact reconstruction (NetworkX isomorphism, with a time limit and a "not checked" result) plus simple differences (node count, edge count, label counts, degree distribution); approximate alignment (label and neighbourhood, Hungarian algorithm), validated by deleting 10% of edges of a known graph.
- Consequence: tile merging (E3) can start directly with visible IDs, as the specification already suggested.

---

## Status of the dataset (21 Oct 2026, unchanged)
- **Version 1 built:** 12 families, sizes 5 to 500 (with the caps of D6), 3 seeds, directed and undirected variants: **822 samples** (411 graphs x 2). Java base files: 138 (in `data/base_full`); samples in `data/samples_full`.
- **Loaded into Neo4j** (container `neo4j-bench`, one database, `sample_id` on every node and edge): 822/822 samples verified by round trip against `graph.json`.
- A 46-sample pilot is in `data/samples`.
- Code in Git: `src/generate_graphs.py` (v5), `src/java/GenerateBase.java`, `src/load_to_neo4j.py`. Data and jar files are not in Git.
- **Does the colour work mean regenerating everything? No.** Colours and line width exist only in the renderer, so the 822 base samples, their Cypher and the Neo4j load stay valid. Only the multi-label set needs a generator change (v6) and its own generation run.
- **Next (1 Nov):** overlap counter and readability flag from `render_info.json` (D9); splits by growth chain (D8); generator v6 for multi-label nodes, with loader and evaluation; prompt design on a dev set (D16), Neo4j check of the answers and the stop reason in the evaluation; a DVC remote; literature reading and the VLM study (E0); bigger models on INSA.

## Status of the pipeline (1 Nov 2026)
- **Done:** JGraphT generator, JSON files, Neo4j load (822/822 round trip), D3 renderer (PNG at 512 / 1024 / 2048 px), local Qwen through Ollama, model runner and evaluator (first versions), DVC stages render, vlm, evaluate on four pilot samples.
- **Code in Git:** `src/render/` (renderer), `src/vlm/` (runner, evaluator, prompts v1 and v2), `dvc.yaml`, `params.yaml`, `configs/pilot_ids.txt`, `dvc.lock`. Data and its cache are not in Git.
- **Not done:** overlap counter, readable flag, splits, multi-label set, dev-set prompt design, Neo4j run of model answers, DVC remote, any run on INSA.

---

## Open

- **D8. Dev / test / train splits.** Samples of one growth chain must stay in the same split (split by chain, not by sample).
- **D15. Number of seeds.** Estimate from the noise measured in the pilot (rough illustration: if F1 varies by 0.15, 3 seeds give about +-0.17, 10 seeds +-0.09, 30 seeds +-0.05).
- **D16. Prompts and run settings (open; first pilot notes 1 Nov).** Prompt templates (direct Cypher vs JSON then convert; zero-shot vs few-shot), temperature, output format, frozen per model.
  - Prompt v1 contained a real example line (`(n1:Person ...)`) and the answers started with exactly that line. Prompt v2 uses placeholders (`<id>`, `<NodeLabel>`), asks to count the circles first, to write each circle once, and to stop after the last edge.
  - Settings used with v2: the values recommended by the official Qwen3-VL model card for vision tasks (temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.5), a fixed seed, and a token cap of 2500. The presence penalty could disturb Cypher, which repeats words by nature; to test with 0.
  - **Pilot results, not results for the paper** (4 directed tree samples with 5, 10, 20 and 30 nodes, 1024 px, 2B model, one run each): Thinking version, 5 nodes: everything right except one reversed arrow; larger sizes ran out of tokens (D27). Instruct, prompt v1 with temperature 0: endless loops (287 predicted nodes for a 5-node graph). Instruct, prompt v2: node counts close to the truth (7, 10, 19 and 29 predicted nodes), node labels right on 5 and 10 nodes (accuracy 1.00), but poor edges (edge F1 0.43 and 0.33): 20 edge lines for 4 real edges on the 5-node sample, and a loop of 189 edge lines on the 10-node one that hit the cap. On 20 and 30 nodes the node list was written again and again until the cap, so no edge was read (edge F1 0).
  - Options still to test: a JSON edge list converted to Cypher by code (RQ3); separate calls for nodes and for edges (shorter answers; changes the design, to discuss with the professor); the 4B model; presence penalty 0.- **D17. Release.** Licence (MIT for code, CC-BY 4.0 for data, as in the specification), data card, versioning. Check with the professor who may publish and under which licence. Note: `load_to_neo4j.py` has the local Docker password as its default value (public repository).
- **D23. Questions asked to the VLM about a graph image (idea kept, not decided).** Database-style questions on top of the graph reconstruction (lookup, counting, neighbours, edge and direction, paths, Cypher-style patterns), scored against answers computed from `graph.json`. To think about later; decisions needed on answer format and on direct answer versus Cypher query.

## Questions for the professor
- Breaking-point cut-off (0.9 / 0.5 proposed).
- INSA cluster: access, GPUs, job time limits.
- Do the graph families and the 500-node bound match what he expects? Is a tree family built by hand (not a JGraphT generator) acceptable?
- Connected graphs only: is that right, or should graphs in several pieces be added?
- Is the milestone date end of October (her notes) or end of November (the specification)?
- Who may publish the code and data, and under which licence? The GitHub repository is public.
- Is Airflow required, or is a lighter tool (DVC) acceptable?
- Square / circle for source / destination: how should it work for nodes that are both?
- Multi-label nodes (new Employee label, two pairs, 20% in a separate set): does this match what he expects?
- Is Qwen3-VL (2B up to 8B, and 32B on INSA) the model family he expects, or another one? Newer Qwen versions with vision exist.
- Thinking and Instruct versions of the same model as two separate conditions: is that a useful comparison for him?
- Where should the DVC data be stored and backed up (INSA storage, an external drive)?
- Can the model be asked for a JSON edge list (converted to Cypher by code), or must the answer be Cypher directly?
