from collections.abc import Callable
from typing import Any

from app.domain.analysis import AnalyzerResult

Incident = dict[str, Any]
EvidenceItem = dict[str, Any]
Analyzer = Callable[[Incident, list[EvidenceItem]], AnalyzerResult]


def _by_source(
    evidence: list[EvidenceItem],
    source: str,
) -> list[EvidenceItem]:
    return [item for item in evidence if item.get("source") == source]


def _raw(item: EvidenceItem) -> dict[str, Any]:
    value = item.get("raw")
    return value if isinstance(value, dict) else {}


def _evidence_ids(items: list[EvidenceItem]) -> list[str]:
    return list(
        dict.fromkeys(
            str(item["evidence_id"])
            for item in items
            if item.get("evidence_id")
        )
    )


def _events(evidence: list[EvidenceItem]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _by_source(evidence, "kubernetes_events"):
        values = _raw(item).get("items", [])
        if isinstance(values, list):
            result.extend(value for value in values if isinstance(value, dict))
    return result


def _containers(evidence: list[EvidenceItem]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _by_source(evidence, "pod_status"):
        values = _raw(item).get("containers", [])
        if isinstance(values, list):
            result.extend(value for value in values if isinstance(value, dict))
    return result


def _states(container: dict[str, Any]) -> list[dict[str, Any]]:
    states = []
    for name in ("state", "last_state"):
        value = container.get(name)
        if isinstance(value, dict):
            states.append(value)
    return states


def _event_text(event: dict[str, Any]) -> str:
    return " ".join(
        str(event.get(name, ""))
        for name in ("reason", "message")
    ).lower()


def _result(
    incident: Incident,
    analyzer: str,
    matched: bool,
    code: str | None,
    confidence: float,
    summary: str,
    supporting: list[EvidenceItem],
    checks: list[str],
    facts: dict[str, Any] | None = None,
) -> AnalyzerResult:
    return AnalyzerResult(
        incident_id=str(incident["id"]),
        analyzer=analyzer,
        matched=matched,
        root_cause_code=code if matched else None,
        confidence=confidence,
        summary=summary,
        evidence_ids=_evidence_ids(supporting),
        suggested_checks=checks,
        facts=facts or {},
    )


def analyze_oom_killed(
    incident: Incident,
    evidence: list[EvidenceItem],
) -> AnalyzerResult:
    pod_items = _by_source(evidence, "pod_status")
    matches: list[dict[str, Any]] = []
    for container in _containers(evidence):
        for state in _states(container):
            reason = str(state.get("reason", ""))
            exit_code = str(state.get("exit_code", ""))
            if reason.lower() == "oomkilled" or exit_code == "137":
                matches.append(
                    {
                        "container": container.get("name"),
                        "reason": reason or None,
                        "exit_code": exit_code or None,
                    }
                )
    matched = bool(matches)
    return _result(
        incident,
        "oom_killed",
        matched,
        "CONTAINER_OOM_KILLED",
        0.98 if matched else 0.0,
        (
            "容器最近一次终止原因为OOMKilled或退出码为137"
            if matched
            else "未发现OOMKilled或退出码137证据"
        ),
        pod_items if matched else [],
        [
            "核对容器memory limit与工作集峰值",
            "确认是内存泄漏、突发流量还是限制设置过低",
        ],
        {"containers": matches},
    )


def analyze_crash_loop(
    incident: Incident,
    evidence: list[EvidenceItem],
) -> AnalyzerResult:
    pod_items = _by_source(evidence, "pod_status")
    event_items = _by_source(evidence, "kubernetes_events")
    containers = []
    for container in _containers(evidence):
        reasons = [
            str(state.get("reason", ""))
            for state in _states(container)
        ]
        if any(reason.lower() == "crashloopbackoff" for reason in reasons):
            containers.append(
                {
                    "name": container.get("name"),
                    "restart_count": container.get("restart_count", 0),
                    "reasons": reasons,
                }
            )
    event_match = any(
        "back-off restarting failed container" in _event_text(event)
        for event in _events(evidence)
    )
    matched = bool(containers) or event_match
    supporting = (pod_items + event_items) if matched else []
    return _result(
        incident,
        "crash_loop_backoff",
        matched,
        "CONTAINER_CRASH_LOOP_BACKOFF",
        0.96 if containers else (0.88 if event_match else 0.0),
        (
            "容器处于CrashLoopBackOff并发生重复重启"
            if matched
            else "未发现CrashLoopBackOff证据"
        ),
        supporting,
        [
            "读取previous logs确认上一次进程退出原因",
            "检查启动命令、环境变量、挂载和依赖服务",
        ],
        {"containers": containers, "restart_event": event_match},
    )


def analyze_image_pull(
    incident: Incident,
    evidence: list[EvidenceItem],
) -> AnalyzerResult:
    pod_items = _by_source(evidence, "pod_status")
    event_items = _by_source(evidence, "kubernetes_events")
    reasons = []
    for container in _containers(evidence):
        for state in _states(container):
            reason = str(state.get("reason", ""))
            if reason.lower() in {"errimagepull", "imagepullbackoff"}:
                reasons.append(reason)
    tokens = (
        "failed to pull image",
        "error: errimagepull",
        "imagepullbackoff",
        "back-off pulling image",
    )
    event_match = any(
        any(token in _event_text(event) for token in tokens)
        for event in _events(evidence)
    )
    matched = bool(reasons) or event_match
    return _result(
        incident,
        "image_pull",
        matched,
        "IMAGE_PULL_FAILED",
        0.97 if reasons else (0.92 if event_match else 0.0),
        (
            "Kubelet无法拉取容器镜像"
            if matched
            else "未发现镜像拉取失败证据"
        ),
        (pod_items + event_items) if matched else [],
        [
            "检查镜像名称、标签和仓库中是否存在该镜像",
            "检查节点到镜像仓库的DNS、代理、证书和认证",
        ],
        {"waiting_reasons": reasons, "pull_event": event_match},
    )


def analyze_probe_failure(
    incident: Incident,
    evidence: list[EvidenceItem],
) -> AnalyzerResult:
    pod_items = _by_source(evidence, "pod_status")
    event_items = _by_source(evidence, "kubernetes_events")
    failed_events = [
        event
        for event in _events(evidence)
        if str(event.get("reason", "")).lower() == "unhealthy"
        and "probe" in _event_text(event)
    ]
    ready_false = any(
        str(condition.get("type")) == "Ready"
        and str(condition.get("status")).lower() == "false"
        for item in pod_items
        for condition in _raw(item).get("conditions", [])
        if isinstance(condition, dict)
    )
    matched = bool(failed_events)
    return _result(
        incident,
        "probe_failure",
        matched,
        "CONTAINER_PROBE_FAILED",
        0.95 if matched and ready_false else (0.90 if matched else 0.0),
        (
            "Kubelet记录了存活或就绪探针失败"
            if matched
            else "未发现明确的探针失败事件"
        ),
        (event_items + pod_items) if matched else [],
        [
            "核对探针path、port、scheme和initialDelaySeconds",
            "从Pod网络命名空间验证探针目标是否可达",
        ],
        {"failed_event_count": len(failed_events), "ready_false": ready_false},
    )


def analyze_pending_scheduling(
    incident: Incident,
    evidence: list[EvidenceItem],
) -> AnalyzerResult:
    pod_items = _by_source(evidence, "pod_status")
    event_items = _by_source(evidence, "kubernetes_events")
    pending = any(
        str(_raw(item).get("phase", "")).lower() == "pending"
        for item in pod_items
    )
    failed_events = [
        event
        for event in _events(evidence)
        if str(event.get("reason", "")).lower() == "failedscheduling"
    ]
    matched = pending and bool(failed_events)
    return _result(
        incident,
        "pending_scheduling",
        matched,
        "POD_SCHEDULING_FAILED",
        0.96 if matched else (0.30 if pending else 0.0),
        (
            "Pod处于Pending且调度器记录了FailedScheduling"
            if matched
            else (
                "Pod为Pending，但缺少FailedScheduling事件"
                if pending
                else "Pod未处于Pending"
            )
        ),
        (pod_items + event_items) if matched else pod_items,
        [
            "检查FailedScheduling消息中的资源、污点和亲和性原因",
            "检查未绑定PVC及StorageClass状态",
        ],
        {"pending": pending, "failed_event_count": len(failed_events)},
    )


def analyze_service_no_endpoints(
    incident: Incident,
    evidence: list[EvidenceItem],
) -> AnalyzerResult:
    service_items = _by_source(evidence, "service_endpoints")
    details = []
    for item in service_items:
        raw = _raw(item)
        selector = raw.get("selector")
        endpoints = raw.get("endpoints")
        if isinstance(selector, dict) and selector and endpoints == []:
            details.append(
                {
                    "resource_ref": item.get("resource_ref"),
                    "selector": selector,
                }
            )
    matched = bool(details)
    return _result(
        incident,
        "service_no_endpoints",
        matched,
        "SERVICE_NO_READY_ENDPOINTS",
        0.90 if matched else 0.0,
        (
            "Service配置了selector但没有可用Endpoint"
            if matched
            else "未发现Service无Endpoint问题"
        ),
        service_items if matched else [],
        [
            "对比Service selector与Pod labels",
            "检查后端Pod Ready状态和EndpointSlice条件",
        ],
        {"services": details},
    )


ANALYZERS: tuple[tuple[str, Analyzer], ...] = (
    ("oom_killed", analyze_oom_killed),
    ("crash_loop_backoff", analyze_crash_loop),
    ("image_pull", analyze_image_pull),
    ("probe_failure", analyze_probe_failure),
    ("pending_scheduling", analyze_pending_scheduling),
    ("service_no_endpoints", analyze_service_no_endpoints),
)
