from collections.abc import Callable

import httpx
from kubernetes.client.exceptions import ApiException
from urllib3.exceptions import HTTPError as Urllib3HTTPError

from app.collectors.kubernetes_collector import (
    get_events,
    get_owner_chain,
    get_pod_logs,
    get_pod_status,
)
from app.collectors.prometheus_collector import query_prometheus
from app.domain.evidence import Evidence, redact_sensitive_text
from app.domain.incident import IncidentStatus
from app.repositories.evidence_repository import (
    list_evidence,
    save_evidence,
)
from app.services.incident_manager import (
    get_incident,
    transition_incident,
)

COLLECTOR_EXCEPTIONS = (
    ApiException,
    httpx.HTTPError,
    Urllib3HTTPError,
    TimeoutError,
    ValueError,
    RuntimeError,
)


def _error_evidence(
    incident_id: str,
    source: str,
    resource_ref: str,
    error: Exception,
) -> Evidence:
    return Evidence(
        incident_id=incident_id,
        source="collector_error",
        resource_ref=resource_ref,
        summary=f"{source} failed: {type(error).__name__}",
        raw={
            "collector": source,
            "error_type": type(error).__name__,
            "message": redact_sensitive_text(str(error))[:1000],
        },
        sensitivity="redacted",
    )


def collect_incident_evidence(incident_id: str) -> list[dict]:
    incident = get_incident(incident_id)
    if incident is None:
        raise KeyError(incident_id)

    if incident["status"] != IncidentStatus.RECEIVED:
        raise ValueError(
            "incident must be RECEIVED before collection, "
            f"got {incident['status']}"
        )

    transition_incident(
        incident_id,
        IncidentStatus.COLLECTING,
        "evidence collection started",
    )

    namespace = incident["namespace"]
    pod = incident["pod"]
    collected: list[Evidence] = []

    tasks: list[tuple[str, str, Callable[[], Evidence]]] = [
        (
            "pod_status",
            f"{namespace}/Pod/{pod}",
            lambda: get_pod_status(
                incident_id,
                namespace,
                pod,
            ),
        ),
        (
            "owner_chain",
            f"{namespace}/Pod/{pod}",
            lambda: get_owner_chain(
                incident_id,
                namespace,
                "Pod",
                pod,
            ),
        ),
        (
            "kubernetes_events",
            f"{namespace}/Object/{pod}",
            lambda: get_events(
                incident_id,
                namespace,
                pod,
            ),
        ),
        (
            "pod_logs",
            f"{namespace}/Pod/{pod}",
            lambda: get_pod_logs(
                incident_id,
                namespace,
                pod,
            ),
        ),
        (
            "pod_restart_increase",
            "Prometheus/pod_restart_increase",
            lambda: query_prometheus(
                incident_id,
                "pod_restart_increase",
                {
                    "namespace": namespace,
                    "pod": pod,
                },
            ),
        ),
        (
            "pod_ready_status",
            "Prometheus/pod_ready_status",
            lambda: query_prometheus(
                incident_id,
                "pod_ready_status",
                {
                    "namespace": namespace,
                    "pod": pod,
                },
            ),
        ),
    ]

    for source, resource_ref, task in tasks:
        try:
            collected.append(task())
        except COLLECTOR_EXCEPTIONS as error:
            collected.append(
                _error_evidence(
                    incident_id,
                    source,
                    resource_ref,
                    error,
                )
            )

    for evidence in collected:
        save_evidence(evidence)

    transition_incident(
        incident_id,
        IncidentStatus.ANALYZING,
        "evidence collection completed",
    )

    return list_evidence(incident_id)
