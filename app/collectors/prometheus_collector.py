import os
import re
from collections.abc import Callable
from typing import Any

import httpx

from app.domain.evidence import Evidence

LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,252}$")


def _safe_label(labels: dict[str, str], name: str) -> str:
    value = labels.get(name, "")
    if not LABEL_PATTERN.fullmatch(value):
        raise ValueError(f"invalid or missing Prometheus label: {name}")
    return value


def _pod_restart_query(labels: dict[str, str]) -> str:
    namespace = _safe_label(labels, "namespace")
    pod = _safe_label(labels, "pod")
    return (
        "sum(increase(kube_pod_container_status_restarts_total"
        f'{{namespace="{namespace}",pod="{pod}"}}[10m]))'
    )


def _pod_cpu_query(labels: dict[str, str]) -> str:
    namespace = _safe_label(labels, "namespace")
    pod = _safe_label(labels, "pod")
    return (
        "sum(rate(container_cpu_usage_seconds_total"
        f'{{namespace="{namespace}",pod="{pod}",container!="",image!=""}}[5m]))'
    )


def _pod_memory_query(labels: dict[str, str]) -> str:
    namespace = _safe_label(labels, "namespace")
    pod = _safe_label(labels, "pod")
    return (
        "sum(container_memory_working_set_bytes"
        f'{{namespace="{namespace}",pod="{pod}",container!="",image!=""}})'
    )


def _pod_ready_query(labels: dict[str, str]) -> str:
    namespace = _safe_label(labels, "namespace")
    pod = _safe_label(labels, "pod")
    return (
        "max(kube_pod_status_ready"
        f'{{namespace="{namespace}",pod="{pod}",condition="true"}})'
    )


def _deployment_unavailable_query(labels: dict[str, str]) -> str:
    namespace = _safe_label(labels, "namespace")
    deployment = _safe_label(labels, "deployment")
    return (
        "kube_deployment_status_replicas_unavailable"
        f'{{namespace="{namespace}",deployment="{deployment}"}}'
    )


QUERY_BUILDERS: dict[str, Callable[[dict[str, str]], str]] = {
    "pod_restart_increase": _pod_restart_query,
    "pod_cpu_usage": _pod_cpu_query,
    "pod_memory_working_set": _pod_memory_query,
    "pod_ready_status": _pod_ready_query,
    "deployment_unavailable_replicas": _deployment_unavailable_query,
}


def build_query(query_id: str, labels: dict[str, str]) -> str:
    builder = QUERY_BUILDERS.get(query_id)
    if builder is None:
        raise ValueError(f"unknown Prometheus query_id: {query_id}")
    return builder(labels)


def query_prometheus(
    incident_id: str,
    query_id: str,
    labels: dict[str, str],
) -> Evidence:
    query = build_query(query_id, labels)
    base_url = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090")
    with httpx.Client(timeout=5.0) as client:
        response = client.get(
            f"{base_url.rstrip('/')}/api/v1/query",
            params={"query": query},
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")
    results = payload.get("data", {}).get("result", [])[:50]
    return Evidence(
        incident_id=incident_id,
        source="prometheus_query",
        resource_ref=f"Prometheus/{query_id}",
        summary=f"query_id={query_id}, series={len(results)}",
        raw={
            "query_id": query_id,
            "query": query,
            "result": results,
        },
    )
