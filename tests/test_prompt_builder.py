import json

from app.services.prompt_builder import (
    MAX_EVIDENCE_ITEMS,
    MAX_RAW_CHARS,
    build_messages,
)


def test_prompt_compacts_evidence_and_output() -> None:
    incident = {
        "id": "inc-prompt",
        "alert_name": "PromptSizeTest",
        "namespace": "fault-lab",
        "workload": "demo",
        "pod": "demo-1",
        "severity": "warning",
        "occurrence_count": 1,
    }

    evidence = [
        {
            "evidence_id": f"ev-{index}",
            "source": "pod_logs",
            "resource_ref": (
                f"fault-lab/Pod/demo-{index}"
            ),
            "summary": "summary-" + ("s" * 1000),
            "raw": {
                "message": "x" * 10000,
            },
        }
        for index in range(20)
    ]

    analysis_results = [
        {
            "analyzer": "crash_loop_backoff",
            "matched": True,
            "root_cause_code": (
                "CONTAINER_CRASH_LOOP_BACKOFF"
            ),
            "confidence": 0.96,
            "summary": "container crash loop",
            "evidence_ids": [
                f"ev-{index}"
                for index in range(12)
            ],
            "suggested_checks": [
                "check previous logs",
                "check command arguments",
                "check exit code",
                "check events",
                "extra check",
            ],
        }
    ]

    messages = build_messages(
        incident,
        evidence,
        analysis_results,
    )
    payload = json.loads(
        messages[1]["content"]
    )

    assert len(payload["evidence"]) == (
        MAX_EVIDENCE_ITEMS
    )

    assert all(
        len(item["untrusted_raw_excerpt"])
        <= MAX_RAW_CHARS
        for item in payload["evidence"]
    )

    assert len(
        payload["analyzer_results"][0][
            "evidence_ids"
        ]
    ) == 8

    assert len(
        payload["analyzer_results"][0][
            "suggested_checks"
        ]
    ) == 4

    assert payload["output_limits"][
        "root_causes_max_items"
    ] == 3

    assert payload["output_limits"][
        "recommended_actions_max_items"
    ] == 4

    assert len(messages[1]["content"]) < 25000
