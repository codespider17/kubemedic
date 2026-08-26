from datetime import UTC, datetime, timedelta
from typing import Any

from app.collectors.kubernetes_client import get_kubernetes_clients
from app.domain.evidence import (
    Evidence,
    redact_sensitive_text,
    truncate_text,
)


def _state_to_dict(state) -> dict[str, Any] | None:
    if state is None:
        return None
    for name in ("waiting", "running", "terminated"):
        value = getattr(state, name, None)
        if value is not None:
            data = {"type": name}
            for field in (
                "reason",
                "message",
                "exit_code",
                "signal",
                "started_at",
                "finished_at",
            ):
                field_value = getattr(value, field, None)
                if field_value is not None:
                    data[field] = str(field_value)
            return data
    return None


def get_pod_status(
    incident_id: str,
    namespace: str,
    pod: str,
) -> Evidence:
    clients = get_kubernetes_clients()
    resource = clients.core.read_namespaced_pod(pod, namespace)
    statuses = []
    for status in resource.status.container_statuses or []:
        statuses.append(
            {
                "name": status.name,
                "ready": status.ready,
                "restart_count": status.restart_count,
                "state": _state_to_dict(status.state),
                "last_state": _state_to_dict(status.last_state),
            }
        )
    conditions = [
        {
            "type": condition.type,
            "status": condition.status,
            "reason": condition.reason,
            "message": condition.message,
        }
        for condition in resource.status.conditions or []
    ]
    raw = {
        "phase": resource.status.phase,
        "node_name": resource.spec.node_name,
        "pod_ip": resource.status.pod_ip,
        "containers": statuses,
        "conditions": conditions,
    }
    restarts = sum(item["restart_count"] for item in statuses)
    return Evidence(
        incident_id=incident_id,
        source="pod_status",
        resource_ref=f"{namespace}/Pod/{pod}",
        summary=(
            f"phase={resource.status.phase}, containers={len(statuses)}, "
            f"restarts={restarts}, node={resource.spec.node_name}"
        ),
        raw=raw,
    )


def _read_workload(namespace: str, kind: str, name: str):
    clients = get_kubernetes_clients()
    normalized = kind.lower()
    if normalized == "pod":
        return clients.core.read_namespaced_pod(name, namespace)
    if normalized == "replicaset":
        return clients.apps.read_namespaced_replica_set(name, namespace)
    if normalized == "deployment":
        return clients.apps.read_namespaced_deployment(name, namespace)
    if normalized == "statefulset":
        return clients.apps.read_namespaced_stateful_set(name, namespace)
    if normalized == "daemonset":
        return clients.apps.read_namespaced_daemon_set(name, namespace)
    if normalized == "job":
        return clients.batch.read_namespaced_job(name, namespace)
    if normalized == "cronjob":
        return clients.batch.read_namespaced_cron_job(name, namespace)
    return None


def get_owner_chain(
    incident_id: str,
    namespace: str,
    kind: str,
    name: str,
    max_depth: int = 5,
) -> Evidence:
    depth_limit = min(max(max_depth, 1), 5)
    chain: list[dict[str, str]] = []
    current_kind = kind
    current_name = name

    for _ in range(depth_limit):
        resource = _read_workload(namespace, current_kind, current_name)
        if resource is None:
            break
        references = resource.metadata.owner_references or []
        if not references:
            break
        owner = next(
            (reference for reference in references if reference.controller),
            references[0],
        )
        chain.append({"kind": owner.kind, "name": owner.name})
        current_kind = owner.kind
        current_name = owner.name

    rendered = " -> ".join(
        [f"{kind}/{name}"]
        + [f"{item['kind']}/{item['name']}" for item in chain]
    )
    return Evidence(
        incident_id=incident_id,
        source="owner_chain",
        resource_ref=f"{namespace}/{kind}/{name}",
        summary=rendered,
        raw={"chain": chain, "max_depth": depth_limit},
    )


def get_events(
    incident_id: str,
    namespace: str,
    resource_name: str,
    since_minutes: int = 15,
) -> Evidence:
    clients = get_kubernetes_clients()
    minutes = min(max(since_minutes, 1), 60)
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    response = clients.core.list_namespaced_event(
        namespace,
        field_selector=f"involvedObject.name={resource_name}",
    )
    events = []
    for event in response.items:
        timestamp = (
            event.event_time
            or event.last_timestamp
            or event.first_timestamp
        )
        if timestamp is not None:
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            if timestamp < cutoff:
                continue
        events.append(
            {
                "type": event.type,
                "reason": event.reason,
                "message": redact_sensitive_text(event.message or ""),
                "count": event.count,
                "timestamp": str(timestamp) if timestamp else None,
            }
        )
    events = events[-50:]
    reasons = sorted({item["reason"] for item in events if item["reason"]})
    return Evidence(
        incident_id=incident_id,
        source="kubernetes_events",
        resource_ref=f"{namespace}/Object/{resource_name}",
        summary=f"events={len(events)}, reasons={','.join(reasons) or 'none'}",
        raw={"since_minutes": minutes, "items": events},
        sensitivity="redacted",
    )


def get_pod_logs(
    incident_id: str,
    namespace: str,
    pod: str,
    container: str | None = None,
    tail_lines: int = 200,
    since_seconds: int = 600,
    previous: bool = False,
) -> Evidence:
    clients = get_kubernetes_clients()
    lines = min(max(tail_lines, 1), 500)
    seconds = min(max(since_seconds, 60), 3600)
    selected_container = container
    if selected_container is None:
        resource = clients.core.read_namespaced_pod(pod, namespace)
        selected_container = resource.spec.containers[0].name
    logs = clients.core.read_namespaced_pod_log(
        pod,
        namespace,
        container=selected_container,
        tail_lines=lines,
        since_seconds=seconds,
        previous=previous,
        timestamps=True,
    )
    sanitized = truncate_text(redact_sensitive_text(logs or ""))
    return Evidence(
        incident_id=incident_id,
        source="pod_logs_previous" if previous else "pod_logs",
        resource_ref=f"{namespace}/Pod/{pod}/{selected_container}",
        summary=(
            f"container={selected_container}, previous={previous}, "
            f"characters={len(sanitized)}"
        ),
        raw={
            "container": selected_container,
            "previous": previous,
            "tail_lines": lines,
            "since_seconds": seconds,
            "log": sanitized,
        },
        sensitivity="redacted",
    )


def get_service_endpoints(
    incident_id: str,
    namespace: str,
    service: str,
) -> Evidence:
    clients = get_kubernetes_clients()
    service_object = clients.core.read_namespaced_service(service, namespace)
    slices = clients.discovery.list_namespaced_endpoint_slice(
        namespace,
        label_selector=f"kubernetes.io/service-name={service}",
    )
    ports = [
        {
            "name": port.name,
            "port": port.port,
            "target_port": str(port.target_port),
            "protocol": port.protocol,
        }
        for port in service_object.spec.ports or []
    ]
    endpoints = []
    for endpoint_slice in slices.items:
        for endpoint in endpoint_slice.endpoints or []:
            endpoints.append(
                {
                    "addresses": endpoint.addresses,
                    "ready": getattr(endpoint.conditions, "ready", None),
                    "target_name": getattr(
                        endpoint.target_ref,
                        "name",
                        None,
                    ),
                }
            )
    return Evidence(
        incident_id=incident_id,
        source="service_endpoints",
        resource_ref=f"{namespace}/Service/{service}",
        summary=f"ports={len(ports)}, endpoints={len(endpoints)}",
        raw={
            "selector": service_object.spec.selector or {},
            "ports": ports,
            "endpoints": endpoints[:100],
        },
    )


def get_node_status(incident_id: str, node: str) -> Evidence:
    clients = get_kubernetes_clients()
    resource = clients.core.read_node(node)
    conditions = [
        {
            "type": condition.type,
            "status": condition.status,
            "reason": condition.reason,
            "message": condition.message,
        }
        for condition in resource.status.conditions or []
    ]
    ready = next(
        (
            condition["status"]
            for condition in conditions
            if condition["type"] == "Ready"
        ),
        "Unknown",
    )
    return Evidence(
        incident_id=incident_id,
        source="node_status",
        resource_ref=f"Node/{node}",
        summary=f"ready={ready}",
        raw={
            "conditions": conditions,
            "capacity": dict(resource.status.capacity or {}),
            "allocatable": dict(resource.status.allocatable or {}),
        },
    )
