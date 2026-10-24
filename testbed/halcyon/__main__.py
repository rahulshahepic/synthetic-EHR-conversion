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
    m = sub.add_parser("mutate", help="derive export B = the same system some weeks later (T-111)")
    m.add_argument("--from", dest="src", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--seed", type=int, default=1)
    m.add_argument("--weeks", type=int, default=6)
    args = p.parse_args()
    if args.cmd == "mutate":
        from .mutate import mutate
        print(json.dumps(mutate(args.src, args.out, args.seed, args.weeks), indent=1))
        return
    print(json.dumps(generate(args.out, args.seed, args.patients, args.as_of, args.profile), indent=1))


if __name__ == "__main__":
    main()
