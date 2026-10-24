"""python -m testbed.halcyon generate --out exports/seed42 --seed 42 --patients 500"""
import argparse
import json
from datetime import date

from .generator import generate
from .profiles import PROFILES


def main() -> None:
    p = argparse.ArgumentParser(prog="halcyon")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="write a synthetic Halcyon export")
    g.add_argument("--out", required=True)
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--patients", type=int, default=500)
    g.add_argument("--as-of", type=date.fromisoformat, default=None)
    g.add_argument("--profile", choices=sorted(PROFILES), default="default",
                   help="source profile whose conventions to generate with")
    args = p.parse_args()
    print(json.dumps(generate(args.out, args.seed, args.patients, args.as_of, args.profile), indent=1))


if __name__ == "__main__":
    main()
