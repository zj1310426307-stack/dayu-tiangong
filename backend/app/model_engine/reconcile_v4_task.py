"""Restricted single-task native-v4 reconciliation command."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from app.database.session import SessionLocal
from app.model_engine.v4_reconciliation import reconcile_v4_task


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect one native-v4 result/artifact pair. The default is read-only; "
            "pass --apply explicitly to perform the reported repair."
        )
    )
    parser.add_argument("--task-id", required=True, type=int)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the bounded repair; omit for dry-run",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        with SessionLocal() as session:
            report = reconcile_v4_task(session, args.task_id, apply=args.apply)
    except (LookupError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "task_id": args.task_id,
                    "mode": "apply" if args.apply else "dry-run",
                    "outcome": "rejected",
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through module execution
    raise SystemExit(main())
