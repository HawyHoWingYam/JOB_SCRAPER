#!/usr/bin/env python3
"""Benchmark the read-only Job search and contextual-facet HTTP interfaces."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from typing import Any

import httpx


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000/api")
    parser.add_argument("--query", default="=ERP")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=24)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--jobs-budget-ms", type=float)
    parser.add_argument("--facets-budget-ms", type=float)
    parser.add_argument("--semantic-budget-ms", type=float)
    parser.add_argument("--hybrid-budget-ms", type=float)
    parser.add_argument(
        "--retrieval-modes",
        nargs="+",
        choices=("lexical", "semantic", "hybrid"),
        default=("lexical", "semantic", "hybrid"),
    )
    args = parser.parse_args()
    if args.runs < 3:
        parser.error("--runs must be at least 3")
    if args.warmups < 0:
        parser.error("--warmups cannot be negative")
    if args.page_size <= 0:
        parser.error("--page-size must be positive")
    return args


def _post_timed(
    client: httpx.Client,
    url: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], float]:
    started_at = time.perf_counter()
    response = client.post(url, json=payload)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected an object response from {url}")
    return data, elapsed_ms


def _sample_endpoint(
    client: httpx.Client,
    url: str,
    payload: dict[str, Any],
    *,
    warmups: int,
    runs: int,
) -> tuple[dict[str, Any], float, list[float]]:
    data, cold_ms = _post_timed(client, url, payload)
    for _ in range(max(0, warmups - 1)):
        data, _ = _post_timed(client, url, payload)
    samples = []
    for _ in range(runs):
        data, elapsed_ms = _post_timed(client, url, payload)
        samples.append(round(elapsed_ms, 3))
    return data, round(cold_ms, 3), samples


def _budget_misses(
    *,
    jobs_median_ms: float,
    facets_median_ms: float,
    jobs_budget_ms: float | None,
    facets_budget_ms: float | None,
) -> list[str]:
    misses = []
    if jobs_budget_ms is not None and jobs_median_ms > jobs_budget_ms:
        misses.append(
            f"jobs median {jobs_median_ms:.3f}ms exceeds {jobs_budget_ms:.3f}ms"
        )
    if facets_budget_ms is not None and facets_median_ms > facets_budget_ms:
        misses.append(
            "facets median "
            f"{facets_median_ms:.3f}ms exceeds {facets_budget_ms:.3f}ms"
        )
    return misses


def main() -> int:
    args = _parse_args()
    base_url = args.base_url.rstrip("/")
    scope = {
        "layers": [
            {
                "client_id": "benchmark-root",
                "text_expression": args.query,
            }
        ]
    }
    corpus_payload = {
        "scope": {"layers": []},
        "retrieval_mode": "lexical",
        "page": 1,
        "page_size": 1,
        "include_facets": False,
    }

    try:
        with httpx.Client(timeout=args.timeout_seconds) as client:
            corpus_data, _ = _post_timed(
                client,
                f"{base_url}/jobs/search",
                corpus_payload,
            )
            scenarios = {}
            for retrieval_mode in args.retrieval_modes:
                jobs_data, jobs_cold_ms, jobs_samples = _sample_endpoint(
                    client,
                    f"{base_url}/jobs/search",
                    {
                        "scope": scope,
                        "retrieval_mode": retrieval_mode,
                        "page": 1,
                        "page_size": args.page_size,
                        "include_facets": False,
                    },
                    warmups=args.warmups,
                    runs=args.runs,
                )
                facets_data, facets_cold_ms, facets_samples = _sample_endpoint(
                    client,
                    f"{base_url}/jobs/search/facets",
                    {"scope": scope, "retrieval_mode": retrieval_mode},
                    warmups=args.warmups,
                    runs=args.runs,
                )
                scenarios[retrieval_mode] = {
                    "jobs": jobs_data,
                    "jobs_samples": jobs_samples,
                    "jobs_cold_ms": jobs_cold_ms,
                    "facets": facets_data,
                    "facets_samples": facets_samples,
                    "facets_cold_ms": facets_cold_ms,
                }
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 2

    misses = []
    scenario_report = {}
    mode_budgets = {
        "lexical": args.jobs_budget_ms,
        "semantic": args.semantic_budget_ms,
        "hybrid": args.hybrid_budget_ms,
    }
    for retrieval_mode, scenario in scenarios.items():
        jobs_median_ms = statistics.median(scenario["jobs_samples"])
        facets_median_ms = statistics.median(scenario["facets_samples"])
        mode_misses = _budget_misses(
            jobs_median_ms=jobs_median_ms,
            facets_median_ms=facets_median_ms,
            jobs_budget_ms=mode_budgets[retrieval_mode],
            facets_budget_ms=args.facets_budget_ms,
        )
        misses.extend(f"{retrieval_mode}: {miss}" for miss in mode_misses)
        jobs_data = scenario["jobs"]
        scenario_report[retrieval_mode] = {
            "result_total": jobs_data.get("total"),
            "page_jobs": len(jobs_data.get("jobs", [])),
            "result_kind": jobs_data.get("result_kind", "exhaustive"),
            "result_limit": jobs_data.get("result_limit"),
            "ranked_candidate_count": jobs_data.get("ranked_candidate_count"),
            "facet_families": sorted(scenario["facets"]),
            "jobs_ms": {
                "samples": scenario["jobs_samples"],
                "cold": scenario["jobs_cold_ms"],
                "median": round(jobs_median_ms, 3),
                "budget": mode_budgets[retrieval_mode],
            },
            "facets_ms": {
                "samples": scenario["facets_samples"],
                "cold": scenario["facets_cold_ms"],
                "median": round(facets_median_ms, 3),
                "budget": args.facets_budget_ms,
            },
        }
    report = {
        "base_url": base_url,
        "query": args.query,
        "corpus_jobs": corpus_data.get("total"),
        "warmups": args.warmups,
        "runs": args.runs,
        "scenarios": scenario_report,
        "budget_misses": misses,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
