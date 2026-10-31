// render.js : graph.json -> image_<res>.png  (D3 force layout + resvg, no browser)
// Usage:
//   node render.js <sample_dir> [--res 512,1024,2048] [--force] [--keep-svg] [--layout-seed 0]
//   node render.js --all <samples_root> [same options]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, forceX, forceY } from "d3-force";
import resvgPkg from "@resvg/resvg-js";
const { Resvg } = resvgPkg;

const RENDERER_VERSION = "1.0";
const PALETTE_VERSION = "2026-10-24-working";
const VIEW = 1000;          // layout/drawing space; resolution is a pure zoom of this
const MARGIN = 45;

// ---- palette (D21, working palette) ----
const NODE_FILL = {
  "Person": "#FFA94D", "City": "#74C0FC", "Company": "#FFFFFF", "Product": "#FFE066",
  "Event": "#FFA8D1", "Employee+Person": "#63E6BE", "City+Event": "#B197FC",
};
const EDGE_COLOR = {
  "KNOWS": "#1FA34A", "LIVES_IN": "#E03131", "WORKS_AT": "#1C64F2",
  "OWNS": "#111111", "LOCATED_IN": "#8B5A2B",
};

// ---- helpers ----
function hash32(str) { // FNV-1a
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const r2 = (x) => Math.round(x * 100) / 100;

function nodeKey(n) {
  const raw = n.labels ?? n.label;
  const arr = Array.isArray(raw) ? raw : [raw];
  return [...arr].sort().join("+");
}

// ---- layout (seeded, same for directed and undirected variants of one graph) ----
function computeLayout(g, layoutSeed) {
  const n = g.nodes.length;
  const ids = g.nodes.map((x) => x.id).sort();
  const und = g.edges
    .map((e) => [e.source, e.target].sort().join(">"))
    .sort();
  const seed = hash32(ids.join(",") + "|" + und.join(",") + "|" + layoutSeed);
  const rnd = mulberry32(seed);

  const nodes = g.nodes.map((x) => ({ id: x.id, x: (rnd() - 0.5) * 300, y: (rnd() - 0.5) * 300 }));
  const idx = new Map(nodes.map((d) => [d.id, d]));
  const links = g.edges
    .filter((e) => e.source !== e.target)
    .map((e) => ({ source: idx.get(e.source), target: idx.get(e.target) }));

  const span = VIEW - 2 * MARGIN;
  const s = span / Math.sqrt(n);              // space per node
  const r = Math.min(0.28 * s, 40);           // node radius in view units
  const sim = forceSimulation(nodes)
    .randomSource(rnd)
    .force("link", forceLink(links).distance(Math.max(2.4 * r, 0.9 * s)).strength(0.7))
    .force("charge", forceManyBody().strength(-Math.max(0.45 * s * s * 0.05, 8)).distanceMax(span))
    .force("collide", forceCollide(r * 1.35))
    .force("x", forceX(0).strength(0.04))
    .force("y", forceY(0).strength(0.04))
    .force("center", forceCenter(0, 0))
    .stop();
  const ticks = n <= 100 ? 400 : 300;
  for (let i = 0; i < ticks; i++) sim.tick();

  // fit to the drawing area, keep aspect ratio, centre it
  const xs = nodes.map((d) => d.x), ys = nodes.map((d) => d.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const w = Math.max(maxX - minX, 1e-6), h = Math.max(maxY - minY, 1e-6);
  const inner = span - 2 * r;
  const k = n === 1 ? 1 : Math.min(inner / w, inner / h);
  const ox = VIEW / 2 - ((minX + maxX) / 2) * k, oy = VIEW / 2 - ((minY + maxY) / 2) * k;
  const pos = {};
  for (const d of nodes) pos[d.id] = [r2(d.x * k + ox), r2(d.y * k + oy)];
  return { pos, r: r2(r), seed };
}

// ---- SVG ----
function buildSvg(g, pos, r) {
  const w = Math.min(Math.max(0.2 * r, 1.0), 3.5);       // edge line width
  const L = Math.max(4.6 * w, 0.55 * r);                 // arrow length (clearly visible)
  const H = 0.42 * L;                                    // arrow half-width
  const directed = !!g.directed;
  const recip = new Set(g.edges.map((e) => e.source + ">" + e.target));
  const out = [];
  out.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${VIEW} ${VIEW}" width="${VIEW}" height="${VIEW}">`);
  out.push(`<rect width="${VIEW}" height="${VIEW}" fill="#FFFFFF"/>`);

  // edges (under the nodes)
  for (const e of g.edges) {
    const col = EDGE_COLOR[e.label];
    if (!col) throw new Error(`unknown edge label: ${e.label}`);
    const [x1, y1] = pos[e.source], [x2, y2] = pos[e.target];
    if (e.source === e.target) { // self-loop: circle above the node
      const lr = 0.75 * r;
      const cx = x1, cy = y1 - r - lr * 0.55;
      out.push(`<circle cx="${r2(cx)}" cy="${r2(cy)}" r="${r2(lr)}" fill="none" stroke="${col}" stroke-width="${r2(w)}"/>`);
      if (directed) {
        const ax = cx + lr * 0.95, ay = cy + lr * 0.35;
        out.push(`<polygon points="${r2(ax)},${r2(ay)} ${r2(ax - H)},${r2(ay - L)} ${r2(ax + H)},${r2(ay - L)}" fill="${col}"/>`);
      }
      continue;
    }
    let dx = x2 - x1, dy = y2 - y1;
    const d = Math.hypot(dx, dy) || 1e-6;
    dx /= d; dy /= d;
    const nx = -dy, ny = dx;                              // normal
    const off = directed && recip.has(e.target + ">" + e.source) ? 1.6 * w + 0.15 * r : 0;
    const sx = x1 + nx * off + dx * r, sy = y1 + ny * off + dy * r;       // start on border
    const tx = x2 + nx * off - dx * r, ty = y2 + ny * off - dy * r;       // tip on border
    if (directed) {
      const bx = tx - dx * L, by = ty - dy * L;           // arrow base
      out.push(`<line x1="${r2(sx)}" y1="${r2(sy)}" x2="${r2(bx)}" y2="${r2(by)}" stroke="${col}" stroke-width="${r2(w)}" stroke-linecap="butt"/>`);
      out.push(`<polygon points="${r2(tx)},${r2(ty)} ${r2(bx + nx * H)},${r2(by + ny * H)} ${r2(bx - nx * H)},${r2(by - ny * H)}" fill="${col}"/>`);
    } else {
      out.push(`<line x1="${r2(sx)}" y1="${r2(sy)}" x2="${r2(tx)}" y2="${r2(ty)}" stroke="${col}" stroke-width="${r2(w)}" stroke-linecap="butt"/>`);
    }
  }

  // nodes + ID text
  const maxLen = Math.max(...g.nodes.map((x) => String(x.id).length));
  for (const nd of g.nodes) {
    const key = nodeKey(nd);
    const fill = NODE_FILL[key];
    if (!fill) throw new Error(`unknown node label: ${key}`);
    const [x, y] = pos[nd.id];
    const sw = key === "Company" ? 0.2 * r : 0.11 * r;
    out.push(`<circle cx="${x}" cy="${y}" r="${r2(r - sw / 2)}" fill="${fill}" stroke="#000000" stroke-width="${r2(sw)}"/>`);
    const fs = Math.min(1.1 * r, (1.55 * r) / (0.68 * maxLen));   // same font size for every node
    out.push(`<text x="${x}" y="${r2(y + fs * 0.35)}" font-family="DejaVu Sans" font-weight="bold" font-size="${r2(fs)}" text-anchor="middle" fill="#000000">${nd.id}</text>`);
  }
  out.push("</svg>");
  return out.join("\n");
}

// ---- one sample ----
function renderSample(dir, opt) {
  const gpath = path.join(dir, "graph.json");
  if (!fs.existsSync(gpath)) throw new Error(`no graph.json in ${dir}`);
  const todo = opt.res.filter((px) => opt.force || !fs.existsSync(path.join(dir, `image_${px}.png`)));
  if (todo.length === 0) return "skipped";
  const g = JSON.parse(fs.readFileSync(gpath, "utf8"));
  const { pos, r, seed } = computeLayout(g, opt.layoutSeed);
  const svg = buildSvg(g, pos, r);
  const here = path.dirname(fileURLToPath(import.meta.url));
  const fontFile = path.join(here, "fonts", "DejaVuSans-Bold.ttf");
  for (const px of todo) {
    const png = new Resvg(svg, {
      fitTo: { mode: "width", value: px },
      background: "#FFFFFF",
      font: { fontFiles: [fontFile], loadSystemFonts: false, defaultFontFamily: "DejaVu Sans" },
    }).render().asPng();
    fs.writeFileSync(path.join(dir, `image_${px}.png`), png);
  }
  if (opt.keepSvg) fs.writeFileSync(path.join(dir, "image.svg"), svg);

  // measurements for the readability flag (D9) and the overlap counter (later)
  const mpath = path.join(dir, "meta.json");
  const meta = fs.existsSync(mpath) ? JSON.parse(fs.readFileSync(mpath, "utf8")) : {};
  const allRes = [...new Set([...(meta.rendering?.resolutions ?? []), ...opt.res])].sort((a, b) => a - b);
  meta.rendering = {
    renderer: "d3-force+resvg", renderer_version: RENDERER_VERSION, palette_version: PALETTE_VERSION,
    layout: "d3-force", layout_seed_option: opt.layoutSeed, layout_seed: seed,
    view_size: VIEW, resolutions: allRes,
    node_radius_view: r,
    node_diameter_px: Object.fromEntries(allRes.map((px) => [String(px), r2((2 * r * px) / VIEW)])),
    positions: pos,
  };
  fs.writeFileSync(mpath, JSON.stringify(meta, null, 2));
  return "rendered " + todo.join(",");
}

// ---- CLI ----
const args = process.argv.slice(2);
const opt = { res: [512, 1024, 2048], force: false, keepSvg: false, layoutSeed: 0 };
let all = false; const targets = [];
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === "--res") opt.res = args[++i].split(",").map(Number);
  else if (a === "--force") opt.force = true;
  else if (a === "--keep-svg") opt.keepSvg = true;
  else if (a === "--layout-seed") opt.layoutSeed = Number(args[++i]);
  else if (a === "--all") all = true;
  else targets.push(a);
}
if (targets.length === 0) { console.error("usage: node render.js <sample_dir> | --all <samples_root> [--res 512,1024] [--force]"); process.exit(1); }

let dirs = targets;
if (all) {
  dirs = fs.readdirSync(targets[0], { withFileTypes: true })
    .filter((d) => d.isDirectory() && fs.existsSync(path.join(targets[0], d.name, "graph.json")))
    .map((d) => path.join(targets[0], d.name)).sort();
}
let ok = 0, skipped = 0, failed = 0;
for (const d of dirs) {
  try {
    const res = renderSample(d, opt);
    if (res === "skipped") skipped++; else { ok++; if (!all) console.log(d, res); }
  } catch (err) { failed++; console.error("FAILED", d, "-", err.message); }
}
console.log(`done: ${ok} rendered, ${skipped} skipped (already exist), ${failed} failed`);
process.exit(failed ? 1 : 0);
