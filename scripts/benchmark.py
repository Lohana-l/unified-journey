"""Benchmark du pipeline Tessera CDP.

Lance chaque étape majeure du pipeline, la chronomètre, et écrit :
  - benchmarks/results.json  (lisible par machine)
  - benchmarks/results.md    (table lisible par un humain, injectée dans le README)

Lancer avec :
    python scripts/benchmark.py            # pipeline complet
    python scripts/benchmark.py --quick    # sauter les étapes lentes (soda)

Chaque étape est une cible Make encapsulée dans un subprocess.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "benchmarks"
OUT_DIR.mkdir(exist_ok=True)

# (nom, cible make, mode rapide ?)
STEPS: list[tuple[str, str, bool]] = [
    ("seed", "seed", True),
    ("ingest", "ingest", True),
    ("transform", "transform", True),
    ("quality", "quality", False),
]


def _run_step(target: str) -> tuple[float, bool]:
    start = time.perf_counter()
    try:
        subprocess.run(
            ["make", target], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        ok = True
    except subprocess.CalledProcessError:
        ok = False
    return time.perf_counter() - start, ok


def _host_info() -> dict:
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor() or platform.machine(),
    }


def _write_markdown(results: list[dict], meta: dict) -> None:
    total = sum(r["seconds"] for r in results if r["ok"])
    lines = [
        "<!-- benchmark:auto-generated -->",
        f"Run at `{meta['run_at']}` on `{meta['host']['os']}` "
        f"(Python {meta['host']['python']}).",
        "",
        "| Step          | Time       | Status |",
        "|---------------|-----------:|:------:|",
    ]
    for r in results:
        t = f"{r['seconds']:6.2f} s" if r["seconds"] < 60 else f"{r['seconds']/60:5.2f} min"
        lines.append(f"| `{r['step']:<12}` | {t:>10} | {'✓' if r['ok'] else '✗'} |")
    lines.append(f"| **total**     | **{total/60:5.2f} min** | |")
    (OUT_DIR / "results.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--quick", action="store_true", help="skip slow steps")
    args = p.parse_args()

    steps = [(n, t) for n, t, q in STEPS if (not args.quick or q)]
    print(f"[bench] running {len(steps)} steps: {', '.join(n for n, _ in steps)}")

    results = []
    for name, target in steps:
        print(f"[bench] {name} …", flush=True)
        seconds, ok = _run_step(target)
        print(f"[bench]   {name}: {seconds:.2f}s {'OK' if ok else 'FAIL'}")
        results.append({"step": name, "seconds": round(seconds, 2), "ok": ok})

    meta = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "host": _host_info(),
        "mode": "quick" if args.quick else "full",
    }
    (OUT_DIR / "results.json").write_text(json.dumps({"meta": meta, "steps": results}, indent=2))
    _write_markdown(results, meta)

    failed = [r for r in results if not r["ok"]]
    print(f"[bench] done. {len(results) - len(failed)} ok, {len(failed)} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
