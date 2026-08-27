#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from app.evaluation import build_evaluation


def fetch_json(
    url: str,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    with urlopen(
        url,
        timeout=timeout_seconds,
    ) as response:
        return json.load(response)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate one completed KubeMedic incident"
        )
    )
    parser.add_argument(
        "--scenario",
        required=True,
        type=Path,
        help="Scenario directory containing expected.json",
    )
    parser.add_argument(
        "--incident-id",
        required=True,
        help="Completed KubeMedic incident ID",
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:5001",
        help="KubeMedic API base URL",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Evaluation JSON output path",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 2 when evaluation fails",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scenario_dir = args.scenario.resolve()
    expected_path = scenario_dir / "expected.json"

    with expected_path.open(
        encoding="utf-8",
    ) as file:
        expected = json.load(file)

    api_base = args.api_base.rstrip("/")
    incident_id = args.incident_id

    incident = fetch_json(
        f"{api_base}/api/v1/incidents/{incident_id}"
    )
    evidence = fetch_json(
        f"{api_base}/api/v1/incidents/"
        f"{incident_id}/evidence"
    )
    analysis = fetch_json(
        f"{api_base}/api/v1/incidents/"
        f"{incident_id}/analysis"
    )
    report = fetch_json(
        f"{api_base}/api/v1/incidents/"
        f"{incident_id}/report"
    )

    result = build_evaluation(
        expected=expected,
        incident=incident,
        evidence=evidence,
        analysis=analysis,
        report=report,
    )

    project_root = Path(__file__).resolve().parent.parent
    output_path = args.output
    if output_path is None:
        output_path = (
            project_root
            / "fault-lab"
            / "results"
            / (
                f"{expected['scenario_id']}-"
                f"{incident_id}-evaluation.json"
            )
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    output_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"RESULT_FILE={output_path}")

    if args.strict and not result["passed"]:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
