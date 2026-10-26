"""CLI: python -m testbed.meridian generate --out exports/meridian [--seed N] [--patients N]"""
import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(prog="testbed.meridian")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--out", required=True)
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--patients", type=int, default=300)
    args = ap.parse_args()

    if args.cmd == "generate":
        from .generator import generate
        print(json.dumps(generate(Path(args.out), seed=args.seed, patients=args.patients), indent=1))


if __name__ == "__main__":
    main()
