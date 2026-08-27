# KubeMedic 实施日志

## 2026-08-26 M0：环境检查

执行主机：k8s-m1
系统版本：Ubuntu 26.04 LTS
目标：在16GB Windows 主机的单台 Ubuntu 虚拟机中运行轻量化 KubeMedic 实验环境。
结果：环境检查通过，项目目录为 `/root/projects/kubemedic`。

## 2026-08-26 M1：K3s 与监控栈

K3s 版本：`v1.36.3+k3s1`
监控 Chart：`kube-prometheus-stack-87.21.0`
结果：单节点 K3s 为 Ready，Prometheus、Alertmanager、kube-state-metrics 和 node-exporter 正常运行。

## 2026-08-26 M2：FastAPI 最小服务

完成 `/healthz`、`/readyz`、`/metrics` 和 Alertmanager Webhook 接口，实现 FastAPI 应用基础结构。后续阶段的完整回归测试最终达到27个测试全部通过。

## 2026-08-26 M8：容器化、Helm 与真实告警闭环

完成 KubeMedic 容器镜像构建及 K3s containerd 导入，使用 Helm 部署 Deployment、Service、ServiceAccount、只读 RBAC、ServiceMonitor 和 SQLite RWO PVC。

Prometheus 测试告警成功进入 firing，Alertmanager 运行配置成功加载 `demo/kubemedic/kubemedic-webhook`，并调用集群内 KubeMedic Webhook。Incident `inc-8be1dfb080ff4973` 自动进入 `REPORTED`。

删除测试 PrometheusRule 后，Alertmanager 在第18次查询时清除活动告警，KubeMedic 在第20次查询时收到 resolved Webhook，同一 Incident 自动进入 `RESOLVED`。

重建 KubeMedic Pod 后，原 Incident 与分析报告仍可查询，SQLite PVC 持久化验证通过。

本阶段验证了告警接入、证据调查、报告生成和恢复状态闭环；受控工具调用与真实故障注入评测属于后续阶段。

## 2026-08-27 M9：F01 CrashLoopBackOff 故障注入评测

完成 `fault-lab` 命名空间、AlertmanagerConfig 和 F01 场景文件，实现 CrashLoopBackOff 真实故障注入、Prometheus 告警、Alertmanager 路由、Incident、Evidence、规则 Analyzer、DeepSeek 报告及恢复验证。

主要分析 Incident 自动采集12条 Evidence，覆盖 `pod_status`、`kubernetes_events`、`pod_logs`、`owner_chain` 和 `prometheus_query`，无 Collector 错误。`crash_loop_backoff` Analyzer 精确命中 `CONTAINER_CRASH_LOOP_BACKOFF`，置信度为0.96；DeepSeek 使用 `deepseek-v4-flash` 生成结构化报告，`provider_error` 为空，总 Token 数为5176。

针对 waiting-reason 指标在 kubelet 重启退避阶段发生的抖动，将告警升级为精确 CrashLoopBackOff 与“异常退出、重启至少三次、当前未 Ready”的复合条件，并归一化动态标签。最终规则持续稳定验证954秒，报告只生成一次，未发生错误 `RESOLVED`。

修复 Incident Manager 的 workload 标签优先级，移除 Prometheus job 候选，发布 `kubemedic:0.6.1`。定向测试6个、完整测试27个全部通过，并通过容器内临时 SQLite 验证新映射逻辑。

稳定性 Incident 跨越 fingerprint Schema 升级，升级前后指纹不同，resolved 回调无法关联旧 Incident。在确认工作负载、Prometheus 和 Alertmanager 均恢复后，通过状态机服务执行一次性人工协调并保留审计事件，未将该次协调记录为自动恢复。

## 2026-08-27 M10：自动评测与周期一致性

新增 `app/evaluation.py`、`fault-lab/evaluate.py` 和 `tests/test_evaluation.py`，实现基于场景期望、Incident、Evidence、Analyzer 和 Report 的只读自动评测。

评测器按照最新一次 `RECEIVED -> REPORTED` 状态周期筛选证据，同时输出 Incident 累计证据数和当前周期证据数，避免同一 Incident 多次重开后发生跨周期数据混算。

使用 Incident `inc-637b687d44274d57` 对 F01 CrashLoopBackOff 进行严格评测。Incident 累计 Evidence 为 18 条，最新周期 Evidence 为 6 条，`cycle_consistent=true`；根因 Top-1、Top-3、必需证据完整性、DeepSeek 报告及恢复状态全部通过。

评测报告记录模型 `deepseek-v4-flash` 的实际 Token 用量为 7485，最终结果为 `passed=true`。完整回归共 31 个测试通过，Ruff 和依赖完整性检查通过。

本阶段只实现对已有实验结果的自动评分，不包含自动故障注入和恢复编排。

## 2026-08-27 M10第二阶段：一键故障实验编排

新增 `app/evaluation_runner.py`、`fault-lab/run_scenario.py`、F01 `runner.json` 和 `tests/test_evaluation_runner.py`，实现带时间边界的Incident选择、阶段化运行结果、超时控制、失败紧急恢复和成功后资源清理。

修复Ruff发现的代码规范问题：配置根对象类型错误改为抛出 `TypeError`；`Callable`改从`collections.abc`导入；泛型等待函数改为Python 3.12+的 `def wait_for_value[T]` 语法。Ruff、依赖检查和38个测试全部通过，无副作用预检通过。

真实运行 `F01-20260827T082300Z`，生成Incident `inc-f6ee4ddb5bb4457c`。从启动到结果保存约142秒，11个阶段全部通过；Prometheus进入firing约65秒，Incident等待到REPORTED约25秒，Incident内部分析周期为18312毫秒。

本轮Evidence共6条，规则Analyzer命中 `CONTAINER_CRASH_LOOP_BACKOFF`，Top-1、Top-3、证据完整性、周期一致性和恢复状态全部通过。

DeepSeek返回 `TerminalDeepSeekError: unexpected finish_reason=length`，系统进入 `rules_fallback`。因此自动闭环判定通过，但本轮不能记录为DeepSeek成功，Token字段保持为 `null`。

实验完成后Prometheus活动告警、Alertmanager活动告警、F01 Deployment和PrometheusRule数量均为0，资源清理验证通过。
