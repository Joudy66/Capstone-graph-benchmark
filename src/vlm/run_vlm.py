"""Send rendered graph images to a local Ollama VLM and save the raw answers.

Run from the repository root. --samples is the folder that holds <id>/image_<res>.png (the render folder). Example:
  python src/vlm/run_vlm.py --samples data/samples_full --out data/pilot_run \
      --ids sample_000301 sample_000303 sample_000307 sample_000309
Only the Python standard library is used. Existing answers are skipped (use --force to redo).
"""
import argparse, base64, hashlib, json, sys, time, urllib.request, urllib.error
from pathlib import Path


def call_ollama(url, model, prompt, image_b64, opts, timeout):
    body = {
        "model": model,
        "stream": False,
        "think": False,   # ask for a direct answer (no long reasoning); retried without if refused
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "options": opts,
    }
    for attempt in (0, 1):
        req = urllib.request.Request(url + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")
            if attempt == 0 and "think" in msg.lower():
                body.pop("think", None)
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ids", nargs="+")
    ap.add_argument("--ids-file", help="text file, one sample id per line (lines starting with # are ignored)")
    ap.add_argument("--res", type=int, default=1024)
    ap.add_argument("--model", default="qwen3-vl:2b")
    ap.add_argument("--prompt", default=str(Path(__file__).with_name("prompt_cypher_v2.txt")))
    ap.add_argument("--url", default="http://localhost:11434")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--num-predict", type=int, default=2500)
    # sampling settings recommended by Qwen for vision tasks (official model card)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--top-p", type=float, default=0.8)
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--presence-penalty", type=float, default=1.5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    ids = list(a.ids or [])
    if a.ids_file:
        ids += [l.strip() for l in Path(a.ids_file).read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.strip().startswith("#")]
    if not ids:
        sys.exit("give --ids or --ids-file")
    prompt = Path(a.prompt).read_text(encoding="utf-8")
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    opts = {"temperature": a.temperature, "top_p": a.top_p, "top_k": a.top_k, "presence_penalty": a.presence_penalty,
            "seed": a.seed, "num_ctx": a.num_ctx, "num_predict": a.num_predict}
    failed = 0
    for sid in ids:
        img = Path(a.samples) / sid / f"image_{a.res}.png"
        out = Path(a.out) / sid
        raw = out / "raw_response.json"
        if raw.exists() and not a.force:
            try:
                old = json.loads(raw.read_text(encoding="utf-8"))
                same = (old.get("model") == a.model and old.get("resolution") == a.res
                        and old.get("options") == opts and old.get("prompt_sha256") == prompt_sha)
            except Exception:
                same = False
            if same:
                print(sid, "skipped (same answer already saved)"); continue
            print(sid, "settings changed since the saved answer: asking again")
        if not img.exists():
            print(sid, "MISSING IMAGE", img); failed += 1; continue
        out.mkdir(parents=True, exist_ok=True)
        print(sid, "asking", a.model, "... (CPU: this can take several minutes)", flush=True)
        t0 = time.time()
        try:
            resp = call_ollama(a.url, a.model, prompt, base64.b64encode(img.read_bytes()).decode(),
                               opts, a.timeout)
        except Exception as e:
            print(sid, "FAILED:", e); failed += 1; continue
        sec = round(time.time() - t0, 1)
        text = resp.get("message", {}).get("content", "")
        raw.write_text(json.dumps({"model": a.model, "resolution": a.res, "prompt_file": Path(a.prompt).name, "prompt_sha256": prompt_sha, "options": opts,
                                   "seconds": sec, "response": resp}, indent=2), encoding="utf-8")
        (out / "answer.txt").write_text(text, encoding="utf-8")
        print(sid, f"done in {sec}s, {len(text)} characters")
    if failed:
        print(f"{failed} sample(s) failed; run again to retry only those")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
