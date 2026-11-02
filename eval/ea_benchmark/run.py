"""EA benchmark: score the whole pipeline (classify -> extract -> merge) against
the practice's own EA sheets, line by line, and compare with the previous run.

    python3 eval/ea_benchmark/run.py --corpus "<folder of client folders>" --label qwen-baseline
    python3 eval/ea_benchmark/run.py --corpus ... --folders 2,7,12 --label quick
    python3 eval/ea_benchmark/run.py --score-only --label rescore   # re-score what's loaded

Each client folder is imported as "BENCH <idx>-<hash>" (never its real name) and
removed again at the start of the next run -- real clients are never touched.
The answer keys (practice EA lines per folder+year) are FROZEN in labels.json on
the first run, so later runs are scored against the same truth even if the
classifier changes; --rebuild-labels refreshes them. labels.json and runs/ hold
real values and are gitignored; the console output is counts only.
"""
import argparse, base64, collections, datetime, hashlib, importlib.util, json, os, subprocess, sys, time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_DATA = os.environ.get("EA_BENCH_DATA") or (
    "/storage/ea_benchmark" if os.path.exists("/.dockerenv") and os.path.isdir("/storage") else HERE)
LABELS = os.path.join(_DATA, "labels.json")
RUNS = os.path.join(_DATA, "runs")
BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8080")
CONTAINER = "intake-backend"
# Inside the backend container (e.g. a Windows box with no host Python): run the
# helper directly instead of through docker. Corpus must then be under /storage.
IN_CONTAINER = os.path.exists("/.dockerenv") and os.path.isdir("/app")
LINES = ["Leistungserloese", "SV 9225", "Kleinmaterial 9100", "Provisionen 9190",
         "Abschreibung 9130", "Sonstiger Aufwand 9230", "Reisekosten 9160"]
STATUSES = ["match", "near", "wrong", "missing", "extra", "both_blank"]


def _importer():
    spec = importlib.util.spec_from_file_location("ipf", os.path.join(ROOT, "scripts", "import_person_folder.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def put_labels(path):
    """Make the labels file visible to the helper as /tmp/ea_labels.json."""
    if IN_CONTAINER:
        import shutil
        shutil.copy(path, "/tmp/ea_labels.json")
    else:
        subprocess.run(["docker", "cp", path, f"{CONTAINER}:/tmp/ea_labels.json"], check=True, capture_output=True)


def helper(*args):
    """Run the in-container helper; return its JSON (the last JSON line -- some
    libraries print warnings to stdout)."""
    if IN_CONTAINER:
        cmd = [sys.executable, os.path.join(HERE, "helper.py"), *args]
    else:
        subprocess.run(["docker", "cp", os.path.join(HERE, "helper.py"), f"{CONTAINER}:/tmp/ea_bench_helper.py"],
                       check=True, capture_output=True)
        cmd = ["docker", "exec", CONTAINER, "python", "/tmp/ea_bench_helper.py", *args]
    out = subprocess.run(cmd, capture_output=True, text=True)
    lines = [l for l in out.stdout.splitlines() if l.startswith("{")]
    if out.returncode or not lines:
        sys.exit(f"helper {args[0]} failed: {out.stderr.strip()[-400:]}")
    return json.loads(lines[-1])


def folders(corpus, only):
    subs = sorted(d for d in os.listdir(corpus) if os.path.isdir(os.path.join(corpus, d)))
    for i, d in enumerate(subs):
        if only is None or i in only:
            yield i, d, f"{i:02d}-{hashlib.sha1(d.encode('utf-8')).hexdigest()[:8]}"


def import_all(corpus, only):
    ipf = _importer()
    for i, d, key in folders(corpus, only):
        files = ipf.collect(os.path.join(corpus, d))
        payload = {"source": "folder-import", "external_ref": f"bench::{key}", "client_name": f"BENCH {key}",
                   "subject": f"Benchmark {key}", "files": files}
        req = urllib.request.Request(BACKEND + "/api/intake/case", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            res = json.load(r)
        print(f"  imported {key}: {res.get('documents')} docs, {res.get('primaries')} to extract")


def wait(stall_min):
    start = time.time()
    while True:
        s = helper("status")
        age = s["last_event_age_s"]
        print(f"  [{int(time.time() - start) // 60:3d} min] pending={s['pending']} extracted={s['extracted']} "
              f"failed={sum(s['failed'].values())}", flush=True)
        if s["pending"] == 0:
            return s, True
        quiet = age if age is not None else time.time() - start
        if quiet > stall_min * 60:
            print(f"  no extraction for {stall_min} min -- scoring what finished (run marked INCOMPLETE)")
            return s, False
        time.sleep(30)


def summarise(results):
    tally = {ln: collections.Counter() for ln in LINES}
    by_src = collections.Counter()
    no_source = []
    for r in results:
        if not r["has_source"]:
            no_source.append(r["key"])
            continue
        for ln in LINES:
            L = r["lines"][ln]
            tally[ln][L["status"]] += 1
            if L["status"] not in ("match", "both_blank"):
                by_src[(ln, L["status"], L["src"])] += 1
    acc = {}
    for ln in LINES:
        n = sum(tally[ln].values())
        acc[ln] = (tally[ln]["match"] + tally[ln]["both_blank"]) / n if n else None
    tot = sum(sum(t.values()) for t in tally.values())
    ok = sum(t["match"] + t["both_blank"] for t in tally.values())
    return {"tally": {k: dict(v) for k, v in tally.items()}, "accuracy": acc,
            "overall": ok / tot if tot else None, "scored_years": len(results) - len(no_source),
            "no_source_years": no_source,
            "non_matches": [[ln, st, src, n] for (ln, st, src), n in by_src.most_common()]}


def show(summary, prev):
    print(f"\nscored client-years: {summary['scored_years']}   "
          f"(skipped, no source docs for that year: {len(summary['no_source_years'])})")
    print(f"{'line':24s}" + "".join(f"{s:>11s}" for s in STATUSES) + "   accuracy   vs prev")
    for ln in LINES:
        t, a = summary["tally"][ln], summary["accuracy"][ln]
        pa = (prev or {}).get("accuracy", {}).get(ln)
        delta = f"{(a - pa) * 100:+6.0f} pt" if a is not None and pa is not None else ""
        print(f"{ln:24s}" + "".join(f"{t.get(s, 0):>11d}" for s in STATUSES)
              + (f"   {a:7.0%}" if a is not None else "        -") + f"   {delta}")
    o, po = summary["overall"], (prev or {}).get("overall")
    print(f"{'OVERALL':24s}" + " " * 66 + (f"   {o:7.0%}" if o is not None else "")
          + (f"   {(o - po) * 100:+6.0f} pt" if o is not None and po is not None else ""))
    if summary["non_matches"]:
        print("\nnon-matches by (line, status, our source doc type):")
        for ln, st, src, n in summary["non_matches"]:
            print(f"  {n:3d}  {ln:24s} {st:8s} src={src}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", help="folder whose sub-folders are one client each")
    ap.add_argument("--folders", help="comma-separated folder indexes (default: all)")
    ap.add_argument("--label", default="run", help="name for this run, e.g. the model or prompt change")
    ap.add_argument("--stall-min", type=float, default=15, help="give up waiting after N quiet minutes")
    ap.add_argument("--rebuild-labels", action="store_true", help="re-freeze answer keys from the sheets")
    ap.add_argument("--score-only", action="store_true", help="don't import; score what's loaded")
    a = ap.parse_args()
    only = {int(x) for x in a.folders.split(",")} if a.folders else None

    complete, status = True, None
    if not a.score_only:
        if not a.corpus or not os.path.isdir(a.corpus):
            sys.exit("--corpus must be the folder that holds the client folders")
        print("cleanup of previous benchmark data:", helper("cleanup"))
        print("importing:")
        import_all(a.corpus, only)
        print("waiting for extraction:")
        status, complete = wait(a.stall_min)

    labels = {} if a.rebuild_labels or not os.path.exists(LABELS) else json.load(open(LABELS))
    os.makedirs(RUNS, exist_ok=True)  # also creates _DATA
    empty = os.path.join(RUNS, ".empty_labels.json")
    with open(empty, "w") as fh:
        fh.write("{}")
    put_labels(LABELS if labels else empty)
    first = helper("score", "/tmp/ea_labels.json")
    new = {k: v for k, v in first["built_labels"].items() if k not in labels}
    if new:
        labels.update(new)
        with open(LABELS, "w") as fh:
            json.dump(labels, fh, indent=1, ensure_ascii=False)
        print(f"\nfroze {len(new)} new answer key(s) into labels.json ({len(labels)} total)")
        put_labels(LABELS)
        first = helper("score", "/tmp/ea_labels.json")
    if only is not None:  # a subset run only scores the folders it loaded
        first["results"] = [r for r in first["results"] if int(r["key"][:2]) in only]

    summary = summarise(first["results"])
    os.makedirs(RUNS, exist_ok=True)
    prev = None
    olds = sorted(f for f in os.listdir(RUNS) if f.endswith(".json"))
    if olds:
        last = json.load(open(os.path.join(RUNS, olds[-1])))
        prev = last.get("summary")
        prev_desc = f"{olds[-1]} (folders: {last.get('folders')})"
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    run = {"label": a.label, "at": ts, "complete": complete, "folders": sorted(only) if only else "all",
           "status": status, "summary": summary, "results": first["results"]}
    path = os.path.join(RUNS, f"{ts}_{a.label}.json")
    with open(path, "w") as fh:
        json.dump(run, fh, indent=1, ensure_ascii=False, default=str)
    show(summary, prev)
    if prev:
        print(f"\n(compared with {prev_desc})")
    if not complete:
        print("\nINCOMPLETE run: some documents were still unread -- treat the numbers as a lower bound.")
    print(f"\nfull run with values (gitignored): {os.path.relpath(path, ROOT)}")


if __name__ == "__main__":
    main()
