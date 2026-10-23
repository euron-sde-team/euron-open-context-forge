"""``python -m contextforge.benchmarks [generate|run]``.

generate  rewrite the committed dataset file from the seeded generators
run       run every method on every case; print markdown, optionally write JSON and markdown
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from contextforge.benchmarks import DATA_FILE, load_cases
from contextforge.benchmarks.datasets import build_cases, to_json
from contextforge.benchmarks.runner import run, to_markdown


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="contextforge.benchmarks")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate")
    p = sub.add_parser("run")
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--markdown", type=Path)
    p.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "generate":
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(to_json(build_cases()) + "\n")
        print(f"wrote {DATA_FILE}")
        return
    version, cases = load_cases()
    report = run(cases, runs=args.runs, dataset_version=version)
    md = to_markdown(report)
    if args.markdown:
        args.markdown.write_text(md)
    if args.json:
        args.json.write_text(report.model_dump_json(indent=1) + "\n")
    sys.stdout.write(md)


if __name__ == "__main__":
    main()
