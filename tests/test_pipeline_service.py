from app.domain.incident import IncidentStatus
from app.services import pipeline_service


def test_pipeline_collects_analyzes_and_reports(monkeypatch) -> None:
    states = iter(
        [
            {"id": "inc-1", "status": IncidentStatus.RECEIVED},
            {"id": "inc-1", "status": IncidentStatus.ANALYZING},
        ]
    )
    calls = []
    monkeypatch.setattr(pipeline_service, "get_incident", lambda _: next(states))
    monkeypatch.setattr(
        pipeline_service,
        "collect_incident_evidence",
        lambda incident_id: calls.append(("collect", incident_id)),
    )
    monkeypatch.setattr(
        pipeline_service,
        "list_analysis_results",
        lambda _: [],
    )
    monkeypatch.setattr(
        pipeline_service,
        "analyze_incident",
        lambda incident_id: calls.append(("analyze", incident_id)),
    )
    monkeypatch.setattr(
        pipeline_service,
        "generate_report",
        lambda incident_id: calls.append(("report", incident_id)),
    )

    pipeline_service.process_incident_pipeline("inc-1")

    assert calls == [
        ("collect", "inc-1"),
        ("analyze", "inc-1"),
        ("report", "inc-1"),
    ]
