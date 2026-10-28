#!/usr/bin/env python3
"""Combine the 14 per-rule Jev Score answers into one weighted semantic score.

Usage:
  semantic_score.py REQUEST.json                  # send the request to TypeSafe (needs TYPESAFE_API_KEY)
  semantic_score.py REQUEST.json --response R.json  # score a saved response instead

Exits 1 when any error rule fired, so it can gate a merge.
"""

import argparse
import json
import os
import sys
import urllib.request

ENDPOINT = "https://api.typesafe.ai/v1/systemone"

# Errors count three times as much as warnings. Tune these to match what your team would decide.
ERROR_WEIGHT = 3.0
WARNING_WEIGHT = 1.0

# Question id prefix -> severity, per the openapi-semantic-review closed catalog.
SEVERITY = {f"sem_{n:03d}": "error" for n in range(1, 8)} | {f"sem_{n:03d}": "warning" for n in range(8, 15)}

# A rule fired when its normalized score reaches this value (0.5 = rounds to "at least one location").
FIRED_THRESHOLD = 0.5


def call_typesafe(request: dict) -> dict:
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        sys.exit("TYPESAFE_API_KEY is not set")
    http_request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(request).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(http_request) as response:
        return json.load(response)


def severity_of(question_id: str) -> str:
    return SEVERITY[question_id[:7]]


def combine(request: dict, response: dict) -> dict:
    rules = []
    weighted_sum = 0.0
    total_weight = 0.0
    for question_id, question in request["questions"].items():
        answer = response["answers"][question_id]
        top_level = len(question["criteria"]) - 1
        normalized = answer["score"] / top_level
        severity = severity_of(question_id)
        weight = ERROR_WEIGHT if severity == "error" else WARNING_WEIGHT
        weighted_sum += weight * normalized
        total_weight += weight
        rules.append({
            "rule": question_id[:7].upper().replace("_", "-"),
            "question": question_id,
            "severity": severity,
            "score": answer["score"],
            "normalized": round(normalized, 3),
            "confidence": answer["confidence"],
            "fired": normalized >= FIRED_THRESHOLD,
        })

    # 0 = no rule violated, 1 = every rule violated at its top level.
    violation = weighted_sum / total_weight
    return {
        "model": response.get("model"),
        "compliance": round(1 - violation, 3),
        "errors_fired": [r["rule"] for r in rules if r["fired"] and r["severity"] == "error"],
        "warnings_fired": [r["rule"] for r in rules if r["fired"] and r["severity"] == "warning"],
        "rules": rules,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("request", help="Jev request JSON with sem_* Score questions")
    parser.add_argument("--response", help="saved Jev response JSON; skips the API call")
    args = parser.parse_args()

    with open(args.request) as f:
        request = json.load(f)
    if args.response:
        with open(args.response) as f:
            response = json.load(f)
    else:
        response = call_typesafe(request)

    result = combine(request, response)
    json.dump(result, sys.stdout, indent=2)
    print()
    sys.exit(1 if result["errors_fired"] else 0)


if __name__ == "__main__":
    main()
