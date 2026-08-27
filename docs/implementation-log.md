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
