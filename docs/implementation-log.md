# KubeMedic 实施与验收记录

## 项目环境

- 操作系统：Ubuntu 26.04 LTS
- Kubernetes：单节点 K3s v1.36.3+k3s1
- 监控栈：kube-prometheus-stack 87.21.0
- 包管理：Helm 4.2.3
- 应用框架：Python、FastAPI
- 持久化：SQLite、Kubernetes PVC
- 大模型：DeepSeek API
- 发布镜像：`docker.io/library/kubemedic:0.6.2`

## 完成内容

KubeMedic 已打通 Prometheus 告警、Alertmanager Webhook、Incident 去重与状态机、Evidence 采集、规则 Analyzer、DeepSeek 结构化 RCA、报告持久化和故障恢复的完整链路。

平台能够根据告警标签定位 Namespace、Pod、Container 和 Workload，采集 Pod 状态、Kubernetes Events、容器日志、Owner Chain、Service Endpoints 与白名单 Prometheus 查询结果。采集内容经过脱敏、截断和结构化后写入 SQLite，并作为规则分析和 DeepSeek 推理的证据来源。

规则引擎已实现以下六类 Analyzer：

- CrashLoopBackOff
- OOMKilled
- ImagePullBackOff
- Probe Failure
- Pending Scheduling
- Service No Endpoints

DeepSeek Provider 使用严格 JSON 输出，限制根因数量、建议数量、未知项数量和 Evidence ID 数量，并校验模型引用的 Evidence ID。模型请求失败、响应被截断或结构不合法时，系统会返回规则 Analyzer 生成的降级报告，保证 Incident 仍能完成调查闭环。

应用已经通过 Docker 镜像和 Helm Chart 部署到 K3s。Chart 包含 Deployment、Service、ServiceAccount、只读 RBAC、SQLite PVC 和 ServiceMonitor。DeepSeek API Key 由 Kubernetes Secret 注入，不写入镜像、源码和实验结果。

## F01 CrashLoopBackOff 自动实验

F01 使用 `node-exporter` 镜像配合无效启动参数制造容器反复退出，通过 PrometheusRule 触发告警，并由 Alertmanager 路由到 KubeMedic。

自动编排器依次完成以下阶段：

1. 环境预检。
2. 清理场景基线。
3. 安装 PrometheusRule。
4. 注入 CrashLoopBackOff 故障。
5. 等待 Prometheus 告警进入 firing。
6. 验证 Alertmanager 路由。
7. 等待 Incident 进入 REPORTED。
8. 应用恢复清单。
9. 等待告警消失和 Incident 进入 RESOLVED。
10. 生成周期一致性与根因命中评测。
11. 清理 Deployment、PrometheusRule 和活动告警。

## 规则降级路径验收

- 运行编号：`F01-20260827T082300Z`
- Incident：`inc-f6ee4ddb5bb4457c`
- 11 个实验阶段全部通过
- 分析模式：`rules_fallback`
- Evidence 数量：6
- Top-1：命中
- Top-3：命中
- Evidence：完整
- Incident 周期：一致
- 故障恢复：通过
- 资源清理：Prometheus 告警、Alertmanager 告警、Deployment 和 PrometheusRule 均为 0

该次实验中 DeepSeek 返回 `finish_reason=length`，系统识别为终止性模型错误并自动生成规则降级报告，验证了模型异常不会阻断告警处理链路。

## DeepSeek 成功路径验收

- 运行编号：`F01-20260827T083839Z`
- Incident：`inc-4e2377a049e44427`
- 11 个实验阶段全部通过
- 根因：`CONTAINER_CRASH_LOOP_BACKOFF`
- 分析模式：`deepseek`
- 模型：`deepseek-v4-flash`
- 分析耗时：4633 ms
- Prompt Tokens：2517
- Completion Tokens：361
- Total Tokens：2878
- Evidence 数量：6
- Top-1：命中
- Top-3：命中
- Evidence：完整
- Incident 周期：一致
- 故障恢复：通过
- Provider Error：无
- 资源清理：Prometheus 告警、Alertmanager 告警、Deployment 和 PrometheusRule 均为 0

## 质量验收

- `ruff check app tests fault-lab/evaluate.py fault-lab/run_scenario.py`：通过
- `pytest -q`：42 个测试全部通过
- `python -m pip check`：无依赖冲突
- `helm lint deploy/helm/kubemedic`：通过
- F01 自动实验：成功路径与规则降级路径均通过
- SQLite PVC：Pod 重建后 Incident 与报告仍可查询
- 只读 RBAC：应用不能读取 Secret，不能删除 Pod
- 敏感信息检查：提交内容未包含 DeepSeek API Key 或私钥

## 项目结论

KubeMedic 已形成可部署、可复现、可评测的 Kubernetes 智能故障调查系统。项目不仅完成了告警到大模型报告的调用链，还实现了确定性证据采集、规则分析、模型失败降级、Incident 生命周期、持久化、真实故障注入、一键恢复和量化验收，能够作为完整的 Kubernetes AIOps 项目进行演示和简历展示。
