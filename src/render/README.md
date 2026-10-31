# Renderer (D20, D21, D26 option C)

Reads `graph.json`, draws the graph with a seeded D3 force layout, writes PNG images.

## Install (once)
    cd src\render
    npm install

## Run
One sample, three resolutions (512, 1024, 2048):

    node render.js ..\..\data\samples\<sample_folder>

Whole folder (skips images that already exist):

    node render.js --all ..\..\data\samples_full

Options: `--res 512,1024` (choose resolutions), `--force` (redraw), `--keep-svg` (also save image.svg), `--layout-seed 1` (a different layout of the same graph).

## What it writes in each sample folder
- `image_512.png`, `image_1024.png`, `image_2048.png`
- `meta.json` -> `rendering`: renderer version, palette version, layout seed, node radius, node diameter in pixels per resolution, and the (x, y) position of every node (drawing space 0..1000). The overlap counter (step 4) will read these positions.

## Rules implemented
- Node fill = node label (working palette of 24 Oct); node centre = ID as stored.
- Edge colour = edge label; no edge text. Arrowhead same colour as the line, larger than the line; none for undirected graphs.
- Layout is seeded from the graph itself (node IDs + undirected edges), so the directed and undirected variants of one graph get the same positions.
- All resolutions are the same drawing zoomed (line widths scale with image size).
- Unknown labels stop the render with an error (nothing is guessed).

## Licences
d3-force: ISC. @resvg/resvg-js: MPL-2.0. DejaVu Sans Bold font (bundled in `fonts/`): free licence of the DejaVu fonts (see fonts/DEJAVU_LICENSE.txt).
