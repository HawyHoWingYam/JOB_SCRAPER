#!/usr/bin/env python3
"""Build the attributed project HSIC V2.0 seed from a reviewed C&SD artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.job_intelligence.company_industry.seed import build_hsic_seed  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    raw_bytes = args.input.read_bytes()
    raw_document = json.loads(raw_bytes)
    seed = build_hsic_seed(
        raw_document,
        retrieved_at=args.retrieved_at,
        raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(seed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
