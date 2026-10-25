"""CLI: python -m testbed.delphi generate --out exports/delphi [--seed N] [--patients N]"""
import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(prog="testbed.delphi")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--out", required=True)
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--patients", type=int, default=500)
    args = ap.parse_args()

    if args.cmd == "generate":
        from .generator import generate
        result = generate(Path(args.out), seed=args.seed, patients=args.patients)
        print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
