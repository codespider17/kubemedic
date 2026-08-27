#!/usr/bin/env python3

import argparse
import json
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from app.evaluation import build_evaluation
from app.evaluation_runner import (
    build_run_result,
    load_runner_config,
    select_run_incident,
)


class ScenarioRunError(RuntimeError):
    pass



RUN_ERRORS = (
    ScenarioRunError,
    TimeoutError,
    HTTPError,
    URLError,
    JSONDecodeError,
    KeyError,
    TypeError,
    ValueError,
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def fetch_json(
    url: str,
    timeout_seconds: int = 15,
) -> Any:
    with urlopen(
        url,
        timeout=timeout_seconds,
    ) as response:
        return json.load(response)


def wait_for_value[T](
    *,
    description: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
    probe: Callable[[], T | None],
) -> T:
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    last_error: str | None = None

    while time.monotonic() < deadline:
        attempt += 1

        try:
            value = probe()
        except (
            HTTPError,
            URLError,
            TimeoutError,
            JSONDecodeError,
        ) as error:
            value = None
            last_error = str(error)

        if value is not None:
            print(
                f"PASS: {description} "
                f"attempt={attempt}"
            )
            return value

        print(
            f"WAIT: {description} "
            f"attempt={attempt}"
        )
        time.sleep(poll_interval_seconds)

    message = (
        f"timeout waiting for {description} "
        f"after {timeout_seconds}s"
    )

    if last_error is not None:
        message = f"{message}; last_error={last_error}"

    raise TimeoutError(message)


class ScenarioRunner:
    def __init__(
        self,
        *,
        scenario_dir: Path,
        api_base: str,
        prometheus_base: str,
        alertmanager_base: str,
        output_dir: Path,
        alert_timeout_seconds: int,
        incident_timeout_seconds: int,
        recovery_timeout_seconds: int,
        poll_interval_seconds: float,
        keep_resources: bool,
    ) -> None:
        self.project_root = (
            Path(__file__).resolve().parent.parent
        )
        self.scenario_dir = scenario_dir.resolve()
        self.api_base = api_base.rstrip("/")
        self.prometheus_base = prometheus_base.rstrip("/")
        self.alertmanager_base = (
            alertmanager_base.rstrip("/")
        )
        self.output_dir = output_dir.resolve()
        self.alert_timeout_seconds = (
            alert_timeout_seconds
        )
        self.incident_timeout_seconds = (
            incident_timeout_seconds
        )
        self.recovery_timeout_seconds = (
            recovery_timeout_seconds
        )
        self.poll_interval_seconds = (
            poll_interval_seconds
        )
        self.keep_resources = keep_resources

        self.expected = self._load_json(
            self.scenario_dir / "expected.json"
        )
        self.config = load_runner_config(
            self.scenario_dir / "runner.json"
        )

        self.scenario_id = str(
            self.expected["scenario_id"]
        )
        timestamp = datetime.now(UTC).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        self.run_id = (
            f"{self.scenario_id}-{timestamp}"
        )

        self.started_at = now_iso()
        self.fault_started_at: str | None = None
        self.incident_id: str | None = None
        self.phases: list[dict[str, Any]] = []
        self.evaluation: dict[str, Any] | None = None
        self.error: str | None = None

        self.namespace_file = (
            self.project_root
            / "fault-lab"
            / "base"
            / "namespace.yaml"
        )
        self.alertmanager_file = (
            self.project_root
            / "fault-lab"
            / "base"
            / "alertmanagerconfig.yaml"
        )
        self.inject_file = (
            self.scenario_dir / "inject.yaml"
        )
        self.recover_file = (
            self.scenario_dir / "recover.yaml"
        )
        self.rule_file = (
            self.scenario_dir / "rule.yaml"
        )

        self._validate_files()

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as file:
            value = json.load(file)

        if not isinstance(value, dict):
            raise TypeError(
                f"JSON root must be an object: {path}"
            )

        return value

    def _validate_files(self) -> None:
        required_files = (
            self.namespace_file,
            self.alertmanager_file,
            self.inject_file,
            self.recover_file,
            self.rule_file,
            self.scenario_dir / "expected.json",
            self.scenario_dir / "runner.json",
        )

        missing = [
            str(path)
            for path in required_files
            if not path.is_file()
        ]

        if missing:
            raise ScenarioRunError(
                "missing required files: "
                + ", ".join(missing)
            )

    @staticmethod
    def _run_kubectl(
        *arguments: str,
        timeout_seconds: int = 240,
    ) -> str:
        command = ["kubectl", *arguments]

        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise ScenarioRunError(
                "kubectl command timed out: "
                + " ".join(command)
            ) from error

        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            detail = stderr or stdout or "unknown error"

            raise ScenarioRunError(
                "kubectl command failed: "
                + " ".join(command)
                + f"; detail={detail}"
            )

        return result.stdout.strip()

    def _execute_phase(
        self,
        name: str,
        action: Callable[[], Any],
    ) -> Any:
        phase_started_at = now_iso()
        print(f"START: phase={name}")

        try:
            detail = action()
        except RUN_ERRORS as error:
            self.phases.append(
                {
                    "name": name,
                    "started_at": phase_started_at,
                    "finished_at": now_iso(),
                    "passed": False,
                    "detail": str(error),
                }
            )
            print(
                f"FAIL: phase={name} "
                f"error={error}"
            )
            raise

        self.phases.append(
            {
                "name": name,
                "started_at": phase_started_at,
                "finished_at": now_iso(),
                "passed": True,
                "detail": detail,
            }
        )
        print(f"PASS: phase={name}")
        return detail

    def _preflight(self) -> dict[str, Any]:
        context = self._run_kubectl(
            "config",
            "current-context",
        )

        namespace = self.config["namespace"]

        namespace_name = self._run_kubectl(
            "get",
            "namespace",
            namespace,
            "-o",
            "jsonpath={.metadata.name}",
        )

        health = fetch_json(
            f"{self.api_base}/healthz"
        )
        prometheus = fetch_json(
            f"{self.prometheus_base}"
            "/api/v1/status/buildinfo"
        )
        alertmanager = fetch_json(
            f"{self.alertmanager_base}"
            "/api/v2/status"
        )

        return {
            "kubernetes_context": context,
            "namespace": namespace_name,
            "kubemedic_health": health,
            "prometheus_status": prometheus.get(
                "status"
            ),
            "alertmanager_cluster_status": (
                alertmanager.get(
                    "cluster",
                    {},
                ).get("status")
            ),
        }

    def preflight_only(self) -> dict[str, Any]:
        return self._execute_phase(
            "preflight",
            self._preflight,
        )

    def _apply_file(self, path: Path) -> str:
        return self._run_kubectl(
            "apply",
            "-f",
            str(path),
        )

    def _delete_rule(self) -> str:
        return self._run_kubectl(
            "-n",
            self.config["rule_namespace"],
            "delete",
            "prometheusrule",
            self.config["rule_name"],
            "--ignore-not-found",
        )

    def _delete_workload(self) -> str:
        return self._run_kubectl(
            "-n",
            self.config["namespace"],
            "delete",
            self.config["workload_kind"],
            self.config["workload_name"],
            "--ignore-not-found",
        )

    def _rollout_status(self) -> str:
        target = (
            f"{self.config['workload_kind']}/"
            f"{self.config['workload_name']}"
        )

        return self._run_kubectl(
            "-n",
            self.config["namespace"],
            "rollout",
            "status",
            target,
            "--timeout=180s",
        )

    def _prometheus_alerts(self) -> list[dict[str, Any]]:
        payload = fetch_json(
            f"{self.prometheus_base}/api/v1/alerts"
        )

        return [
            alert
            for alert in payload.get(
                "data",
                {},
            ).get("alerts", [])
            if alert.get("labels", {}).get(
                "alertname"
            )
            == self.config["alert_name"]
        ]

    def _alertmanager_alerts(
        self,
    ) -> list[dict[str, Any]]:
        payload = fetch_json(
            f"{self.alertmanager_base}"
            "/api/v2/alerts"
        )

        if not isinstance(payload, list):
            raise TypeError(
                "Alertmanager alerts response "
                "must be a list"
            )

        return [
            alert
            for alert in payload
            if alert.get("labels", {}).get(
                "alertname"
            )
            == self.config["alert_name"]
        ]

    def _wait_external_alerts_clear(
        self,
    ) -> dict[str, int]:
        def probe() -> dict[str, int] | None:
            prometheus_count = len(
                self._prometheus_alerts()
            )
            alertmanager_count = len(
                self._alertmanager_alerts()
            )

            print(
                "STATE: "
                f"prometheus={prometheus_count} "
                f"alertmanager={alertmanager_count}"
            )

            if (
                prometheus_count == 0
                and alertmanager_count == 0
            ):
                return {
                    "prometheus_alerts": 0,
                    "alertmanager_alerts": 0,
                }

            return None

        return wait_for_value(
            description="external alerts clear",
            timeout_seconds=(
                self.recovery_timeout_seconds
            ),
            poll_interval_seconds=(
                self.poll_interval_seconds
            ),
            probe=probe,
        )

    def _prepare_baseline(self) -> dict[str, Any]:
        namespace_result = self._apply_file(
            self.namespace_file
        )
        route_result = self._apply_file(
            self.alertmanager_file
        )
        self._delete_rule()
        recover_result = self._apply_file(
            self.recover_file
        )
        rollout_result = self._rollout_status()
        clear_result = (
            self._wait_external_alerts_clear()
        )

        return {
            "namespace": namespace_result,
            "alertmanager_route": route_result,
            "recover": recover_result,
            "rollout": rollout_result,
            "alerts": clear_result,
        }

    def _prometheus_rule_probe(
        self,
    ) -> dict[str, Any] | None:
        payload = fetch_json(
            f"{self.prometheus_base}/api/v1/rules"
        )

        for group in payload.get(
            "data",
            {},
        ).get("groups", []):
            for rule in group.get("rules", []):
                if (
                    rule.get("name")
                    == self.config["alert_name"]
                ):
                    return {
                        "name": rule.get("name"),
                        "state": rule.get("state"),
                        "health": rule.get("health"),
                        "last_error": rule.get(
                            "lastError"
                        ),
                    }

        return None

    def _install_rule(self) -> dict[str, Any]:
        apply_result = self._apply_file(
            self.rule_file
        )

        loaded_rule = wait_for_value(
            description="Prometheus rule loaded",
            timeout_seconds=(
                self.alert_timeout_seconds
            ),
            poll_interval_seconds=(
                self.poll_interval_seconds
            ),
            probe=self._prometheus_rule_probe,
        )

        return {
            "apply": apply_result,
            "rule": loaded_rule,
        }

    def _inject(self) -> dict[str, str]:
        self.fault_started_at = now_iso()
        apply_result = self._apply_file(
            self.inject_file
        )

        return {
            "fault_started_at": (
                self.fault_started_at
            ),
            "apply": apply_result,
        }

    def _prometheus_firing_probe(
        self,
    ) -> dict[str, Any] | None:
        for alert in self._prometheus_alerts():
            if alert.get("state") == "firing":
                return {
                    "state": alert.get("state"),
                    "labels": alert.get("labels"),
                    "active_at": alert.get(
                        "activeAt"
                    ),
                }

        return None

    def _alertmanager_active_probe(
        self,
    ) -> dict[str, Any] | None:
        for alert in self._alertmanager_alerts():
            state = alert.get(
                "status",
                {},
            ).get("state")

            receiver_names = [
                receiver.get("name", "")
                for receiver in alert.get(
                    "receivers",
                    [],
                )
            ]

            routed_to_kubemedic = any(
                "kubemedic" in name
                for name in receiver_names
            )

            if (
                state == "active"
                and routed_to_kubemedic
            ):
                return {
                    "state": state,
                    "receivers": receiver_names,
                    "labels": alert.get("labels"),
                }

        return None

    def _wait_prometheus_firing(
        self,
    ) -> dict[str, Any]:
        return wait_for_value(
            description="Prometheus alert firing",
            timeout_seconds=(
                self.alert_timeout_seconds
            ),
            poll_interval_seconds=(
                self.poll_interval_seconds
            ),
            probe=self._prometheus_firing_probe,
        )

    def _wait_alertmanager_active(
        self,
    ) -> dict[str, Any]:
        return wait_for_value(
            description=(
                "Alertmanager alert routed "
                "to KubeMedic"
            ),
            timeout_seconds=(
                self.alert_timeout_seconds
            ),
            poll_interval_seconds=(
                self.poll_interval_seconds
            ),
            probe=self._alertmanager_active_probe,
        )

    def _incident_probe(
        self,
    ) -> dict[str, Any] | None:
        if self.fault_started_at is None:
            raise ScenarioRunError(
                "fault start time is not set"
            )

        payload = fetch_json(
            f"{self.api_base}"
            "/api/v1/incidents?limit=200"
        )
        items = payload.get("items", [])

        incident = select_run_incident(
            items,
            alert_name=self.config["alert_name"],
            namespace=self.config["namespace"],
            run_started_at=self.fault_started_at,
        )

        if incident is None:
            return None

        self.incident_id = str(incident["id"])
        return incident

    def _wait_incident_reported(
        self,
    ) -> dict[str, Any]:
        return wait_for_value(
            description="Incident reported",
            timeout_seconds=(
                self.incident_timeout_seconds
            ),
            poll_interval_seconds=(
                self.poll_interval_seconds
            ),
            probe=self._incident_probe,
        )

    def _recover(self) -> dict[str, Any]:
        apply_result = self._apply_file(
            self.recover_file
        )
        rollout_result = self._rollout_status()

        return {
            "apply": apply_result,
            "rollout": rollout_result,
        }

    def _resolved_incident_probe(
        self,
    ) -> dict[str, Any] | None:
        if self.incident_id is None:
            raise ScenarioRunError(
                "incident ID is not set"
            )

        incident = fetch_json(
            f"{self.api_base}/api/v1/incidents/"
            f"{self.incident_id}"
        )

        if incident.get("status") == "RESOLVED":
            return incident

        print(
            "STATE: "
            f"incident={self.incident_id} "
            f"status={incident.get('status')}"
        )
        return None

    def _wait_recovered(
        self,
    ) -> dict[str, Any]:
        external = self._wait_external_alerts_clear()

        incident = wait_for_value(
            description="Incident resolved",
            timeout_seconds=(
                self.recovery_timeout_seconds
            ),
            poll_interval_seconds=(
                self.poll_interval_seconds
            ),
            probe=self._resolved_incident_probe,
        )

        return {
            "external_alerts": external,
            "incident_status": incident.get(
                "status"
            ),
            "resolved_at": incident.get(
                "resolved_at"
            ),
        }

    def _evaluate(self) -> dict[str, Any]:
        if self.incident_id is None:
            raise ScenarioRunError(
                "incident ID is not set"
            )

        incident = fetch_json(
            f"{self.api_base}/api/v1/incidents/"
            f"{self.incident_id}"
        )
        evidence = fetch_json(
            f"{self.api_base}/api/v1/incidents/"
            f"{self.incident_id}/evidence"
        )
        analysis = fetch_json(
            f"{self.api_base}/api/v1/incidents/"
            f"{self.incident_id}/analysis"
        )
        report = fetch_json(
            f"{self.api_base}/api/v1/incidents/"
            f"{self.incident_id}/report"
        )

        self.evaluation = build_evaluation(
            expected=self.expected,
            incident=incident,
            evidence=evidence,
            analysis=analysis,
            report=report,
        )

        return self.evaluation

    def _cleanup(self) -> dict[str, Any]:
        if self.keep_resources:
            return {
                "skipped": True,
                "reason": "--keep-resources",
            }

        rule_result = self._delete_rule()
        workload_result = self._delete_workload()

        return {
            "skipped": False,
            "rule": rule_result,
            "workload": workload_result,
        }

    def emergency_cleanup(self) -> None:
        phase_started_at = now_iso()

        try:
            recover_result = self._apply_file(
                self.recover_file
            )
            rollout_result = self._rollout_status()

            if self.keep_resources:
                detail = {
                    "recover": recover_result,
                    "rollout": rollout_result,
                    "resources_deleted": False,
                }
            else:
                detail = {
                    "recover": recover_result,
                    "rollout": rollout_result,
                    "rule": self._delete_rule(),
                    "workload": (
                        self._delete_workload()
                    ),
                    "resources_deleted": True,
                }

            self.phases.append(
                {
                    "name": "emergency_cleanup",
                    "started_at": phase_started_at,
                    "finished_at": now_iso(),
                    "passed": True,
                    "detail": detail,
                }
            )
        except ScenarioRunError as error:
            self.phases.append(
                {
                    "name": "emergency_cleanup",
                    "started_at": phase_started_at,
                    "finished_at": now_iso(),
                    "passed": False,
                    "detail": str(error),
                }
            )

    def run(self) -> dict[str, Any]:
        self._execute_phase(
            "preflight",
            self._preflight,
        )
        self._execute_phase(
            "prepare_baseline",
            self._prepare_baseline,
        )
        self._execute_phase(
            "install_rule",
            self._install_rule,
        )
        self._execute_phase(
            "inject_fault",
            self._inject,
        )
        self._execute_phase(
            "prometheus_firing",
            self._wait_prometheus_firing,
        )
        self._execute_phase(
            "alertmanager_routed",
            self._wait_alertmanager_active,
        )
        self._execute_phase(
            "incident_reported",
            self._wait_incident_reported,
        )
        self._execute_phase(
            "recover_workload",
            self._recover,
        )
        self._execute_phase(
            "wait_recovered",
            self._wait_recovered,
        )
        self._execute_phase(
            "evaluate",
            self._evaluate,
        )
        self._execute_phase(
            "cleanup",
            self._cleanup,
        )

        return self.build_result()

    def build_result(self) -> dict[str, Any]:
        return build_run_result(
            run_id=self.run_id,
            scenario_id=self.scenario_id,
            started_at=self.started_at,
            finished_at=now_iso(),
            incident_id=self.incident_id,
            phases=self.phases,
            evaluation=self.evaluation,
            error=self.error,
        )

    def write_result(
        self,
        result: dict[str, Any],
    ) -> Path:
        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            self.output_dir
            / f"{self.run_id}-run.json"
        )
        temporary_path = output_path.with_suffix(
            ".json.tmp"
        )

        temporary_path.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(output_path)
        return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run one bounded KubeMedic fault scenario"
        )
    )
    parser.add_argument(
        "--scenario",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:5001",
    )
    parser.add_argument(
        "--prometheus-base",
        default="http://127.0.0.1:9090",
    )
    parser.add_argument(
        "--alertmanager-base",
        default="http://127.0.0.1:9093",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("fault-lab/results"),
    )
    parser.add_argument(
        "--alert-timeout",
        type=int,
        default=300,
    )
    parser.add_argument(
        "--incident-timeout",
        type=int,
        default=420,
    )
    parser.add_argument(
        "--recovery-timeout",
        type=int,
        default=480,
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
    )
    parser.add_argument(
        "--keep-resources",
        action="store_true",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        runner = ScenarioRunner(
            scenario_dir=args.scenario,
            api_base=args.api_base,
            prometheus_base=args.prometheus_base,
            alertmanager_base=args.alertmanager_base,
            output_dir=args.output_dir,
            alert_timeout_seconds=args.alert_timeout,
            incident_timeout_seconds=(
                args.incident_timeout
            ),
            recovery_timeout_seconds=(
                args.recovery_timeout
            ),
            poll_interval_seconds=(
                args.poll_interval
            ),
            keep_resources=args.keep_resources,
        )
    except RUN_ERRORS as error:
        print(f"STOP: runner初始化失败: {error}")
        return 2

    if args.preflight_only:
        try:
            result = runner.preflight_only()
        except RUN_ERRORS as error:
            print(f"STOP: 预检失败: {error}")
            return 2

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )
        print("PASS: 自动编排器预检通过")
        return 0

    try:
        result = runner.run()
    except RUN_ERRORS as error:
        runner.error = str(error)
        runner.emergency_cleanup()
        result = runner.build_result()

    output_path = runner.write_result(result)

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
