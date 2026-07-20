"""CLI: python -m identity.council_souls verify

D087 Phase 2.10 — cold-clone operator check (zero HTML, no network).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m identity.council_souls",
        description=(
            "Council soul pack tools. "
            "'verify' = cold-clone operator go/no-go (D087 Phase 2.10)."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_verify = sub.add_parser(
        "verify",
        help="Operator cold-clone check: souls + self_host docs + freeze",
    )
    p_verify.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repo root (default: package parents → artisan root)",
    )
    p_verify.add_argument(
        "--json",
        action="store_true",
        help="Print machine JSON only (default when stdout is not a TTY)",
    )

    p_status = sub.add_parser("status", help="Print council_status() only")
    p_status.add_argument("--root", type=Path, default=None)

    args = parser.parse_args(argv)

    # Ensure repo root is importable when invoked as python -m from elsewhere.
    if args.root is not None:
        root = args.root.resolve()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
    else:
        root = None

    from identity.council_souls import council_status, operator_verify

    if args.cmd == "status":
        out = council_status(root)
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0 if out.get("council_present") else 2

    if args.cmd == "verify":
        report = operator_verify(root)
        as_json = bool(args.json) or not sys.stdout.isatty()
        if as_json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(
                f"ready_local_elect_host={report['ready_local_elect_host']} "
                f"public_ship_authorized={report['public_ship_authorized']} "
                f"failed={report['failed']}"
            )
            for c in report["checks"]:
                mark = "PASS" if c["ok"] else "FAIL"
                print(f"  [{mark}] {c['id']}: {c.get('detail') or ''}")
            print(report.get("note") or "")
        if not report.get("ready_local_elect_host"):
            return 2
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
