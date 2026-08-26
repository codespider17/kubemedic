# KubeMedic实施日志

## M0 环境检查

日期：
执行主机：k8s-m1
系统版本：Ubuntu 26.04 LTS
目标：记录基础环境与项目版本
关键输出：
是否通过：
问题与处理：

## M1 K3s与监控栈

日期：
实际K3s版本：v1.36.3+k3s1
实际Helm版本：
监控Chart版本：
关键输出：
是否通过：
问题与处理：

## M2 FastAPI最小服务

日期：
Python版本：
目标：完成健康接口和Alertmanager Webhook
测试结果：
是否通过：
问题与处理：

## 2026-08-26 M8：容器化、Helm 与真实告警闭环

完成 KubeMedic 容器镜像构建及 K3s containerd 导入，使用 Helm 部署 Deployment、Service、ServiceAccount、只读 RBAC、ServiceMonitor 和 SQLite RWO PVC。

Prometheus 测试告警成功进入 firing，Alertmanager 运行配置成功加载 demo/kubemedic/kubemedic-webhook，并调用集群内 KubeMedic Webhook。Incident inc-8be1dfb080ff4973 自动进入 REPORTED。

删除测试 PrometheusRule 后，Alertmanager 在第 18 次查询时清除活动告警，KubeMedic 在第 20 次查询时收到 resolved Webhook，同一 Incident 自动进入 RESOLVED。

重建 KubeMedic Pod 后，原 Incident 与分析报告仍可查询，SQLite PVC 持久化验证通过。

本阶段验证的是告警接入、证据调查、报告生成和恢复状态闭环；受控工具调用与真实故障注入评测仍属于后续阶段。
