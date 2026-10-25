"""python -m nimbus serve --db nimbus.db --port 8700"""
import argparse

import uvicorn

from .api import create_app
from .service import NimbusService


def main() -> None:
    p = argparse.ArgumentParser(prog="nimbus")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the Nimbus API")
    s.add_argument("--db", default="nimbus.db")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8700)
    s.add_argument("--no-access-log", action="store_true", help="don't log every request (benchmarks)")
    args = p.parse_args()
    uvicorn.run(create_app(NimbusService(args.db)), host=args.host, port=args.port, access_log=not args.no_access_log)


if __name__ == "__main__":
    main()
