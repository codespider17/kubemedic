# KubeMedic

基于 Kubernetes、Prometheus、Alertmanager 与 DeepSeek API 的证据驱动智能故障调查与自动评测平台。

KubeMedic 将真实 Kubernetes 告警转换为可追踪的 Incident，自动采集集群状态、Events、容器日志和 Prometheus 指标，通过确定性规则 Analyzer 生成根因候选，再由 DeepSeek 输出带 Evidence 引用、置信度和处置建议的结构化 RCA 报告。系统同时提供模型失败降级、故障恢复验证、自动评分和实验资源清理能力。

## 系统架构

```text
PrometheusRule
  → Prometheus firing
  → Alertmanager Webhook
  → Incident 去重与状态机
  → Kubernetes / Prometheus Evidence 采集
  → 规则 Analyzer
  → DeepSeek 结构化 RCA
  → REPORTED
  → 场景恢复与 resolved Webhook
  → RESOLVED
  → Top-1 / Top-3 / Evidence / Token 自动评测
  → 实验资源清理
```

## 核心能力

- 接收 Alertmanager Webhook，规范化告警并按照稳定指纹完成 Incident 去重。
- 使用 `RECEIVED`、`COLLECTING`、`ANALYZING`、`REPORTED`、`RESOLVED` 状态记录完整故障生命周期。
- 采集 Pod状态、Owner关系、Events、容器日志、Service、EndpointSlice和Prometheus指标，统一保存为带`evidence_id`的Evidence。
- 使用预定义`query_id`构造PromQL，拒绝把任意模型输出直接作为Prometheus查询执行。
- 内置6类确定性规则Analyzer，为大模型提供可解释的根因候选和证据锚点。
- 调用DeepSeek生成严格JSON报告，并校验Incident ID、根因编码、Evidence引用和Pydantic Schema。
- DeepSeek异常时自动生成`rules_fallback`报告，保持告警分析和恢复闭环可用。
- 使用SQLite保存Incident、Evidence、Analyzer结果、状态事件和报告，通过RWO PVC验证Pod重建后的数据持久化。
- 使用场景编排器自动执行健康基线、故障注入、告警等待、报告生成、恢复验证、评分和清理。
- 提供`/healthz`、`/readyz`、`/metrics`与ServiceMonitor，支持Kubernetes探针和Prometheus抓取。
- 使用Helm部署ServiceAccount、只读RBAC、Deployment、Service、PVC和ServiceMonitor。

## 规则 Analyzer

| Analyzer | 根因编码 | 识别场景 |
| --- | --- | --- |
| `oom_killed` | `CONTAINER_OOM_KILLED` | 容器因内存不足终止 |
| `crash_loop_backoff` | `CONTAINER_CRASH_LOOP_BACKOFF` | 容器反复启动失败 |
| `image_pull` | `IMAGE_PULL_FAILED` | 镜像拉取或鉴权失败 |
| `probe_failure` | `CONTAINER_PROBE_FAILED` | 存活或就绪探针失败 |
| `pending_scheduling` | `POD_SCHEDULING_FAILED` | Pod无法完成调度 |
| `service_no_endpoints` | `SERVICE_NO_READY_ENDPOINTS` | Service没有可用后端端点 |

## 自动故障实验

项目使用F01 CrashLoopBackOff场景完成真实集群闭环：向缓存的node-exporter镜像传入无效启动参数，使容器持续退出；Prometheus复合规则结合waiting reason、上次终止原因、重启次数和Ready状态识别故障，避免容器重启瞬间造成告警抖动。

`fault-lab/run_scenario.py`将实验拆分为11个有界阶段：

```text
preflight
prepare_baseline
install_rule
inject_fault
prometheus_firing
alertmanager_routed
incident_reported
recover_workload
wait_recovered
evaluate
cleanup
```

每个阶段保存开始时间、结束时间、通过状态和关键结果。等待操作具有明确超时；异常时执行紧急恢复；成功后删除实验Deployment和PrometheusRule。

## 已验证结果

| 实验 | 分析模式 | 关键结果 |
| --- | --- | --- |
| `F01-20260827T082300Z` | `rules_fallback` | DeepSeek返回`finish_reason=length`后，规则Analyzer仍命中根因并完成恢复、评测和清理 |
| `F01-20260827T083839Z` | `deepseek` | 11阶段全部通过，分析耗时4633ms，Prompt 2517 Token，Completion 361 Token，总计2878 Token |

DeepSeek成功实验生成Incident `inc-4e2377a049e44427`，本轮6条Evidence全部位于同一分析周期；`CONTAINER_CRASH_LOOP_BACKOFF`的Top-1、Top-3、Evidence完整性和周期一致性全部通过，`provider_error=null`。

两次实验结束后均确认Prometheus活动告警、Alertmanager活动告警、F01 Deployment和PrometheusRule数量为0。上述数据来自单次可复现实验结果，不作为长期平均性能声明。

## DeepSeek结构化输出治理

- 显式设置`response_format={"type":"json_object"}`。
- 默认关闭DeepSeek v4思考模式，避免结构化RCA消耗无关推理Token。
- 将输出上限设置为2400 Token，并限制Evidence、原文、根因、建议和unknowns的数量与长度。
- 对日志、事件、注解和错误消息进行不可信数据标记与敏感字段脱敏。
- Provider失败、非法JSON、Schema错误和Evidence幻觉均进入规则降级路径。

## 安全设计

- DeepSeek API Key只通过Kubernetes Secret注入，不写入镜像、SQLite、配置文件或Git。
- KubeMedic ServiceAccount只拥有故障调查所需的只读权限，不能读取Secret或删除Pod。
- DeepSeek只接收裁剪、脱敏、带引用约束的Evidence，不直接执行Shell、kubectl或集群写操作。
- 恢复动作由固定场景中的`recover.yaml`和编排器执行，目标资源由`runner.json`明确限定。
- Prometheus查询来自代码内预定义模板，不执行模型生成的任意PromQL。

## 技术栈

- Kubernetes：K3s、Helm、containerd
- 监控告警：Prometheus、Alertmanager、kube-prometheus-stack
- 后端：Python、FastAPI、Pydantic、Kubernetes Python Client
- 存储：SQLite、local-path PVC
- 大模型：DeepSeek API、OpenAI兼容SDK
- 质量：pytest、Ruff、pip check、helm lint
- 镜像：Podman、`python3.12-bookworm-slim`

## 项目结构

```text
kubemedic/
├── app/
│   ├── analyzers/          # 规则Analyzer与执行引擎
│   ├── api/                # Alert、Incident、Evidence、Report API
│   ├── collectors/         # Kubernetes与Prometheus证据采集
│   ├── domain/             # Incident、Evidence、Analysis、Report模型
│   ├── providers/          # DeepSeek Provider
│   ├── repositories/       # SQLite数据访问
│   ├── services/           # 调查流水线、Prompt与报告服务
│   ├── evaluation.py       # 周期一致性自动评分
│   └── main.py             # FastAPI入口与观测端点
├── deploy/
│   ├── alertmanager/
│   ├── demo-app/
│   ├── helm/kubemedic/
│   ├── rbac/
│   └── monitoring-values.yaml
├── fault-lab/
│   ├── base/               # 实验命名空间与告警路由
│   ├── scenarios/          # F01注入、恢复、规则与运行配置
│   ├── results/            # 脱敏后的真实实验结果
│   ├── evaluate.py         # 已有Incident自动评分
│   └── run_scenario.py     # 一键实验编排器
├── tests/
├── Dockerfile
├── pyproject.toml
└── README.md
```

## 本地开发与测试

```bash
git clone git@github.com:codespider17/kubemedic.git
cd kubemedic

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'

ruff check app tests fault-lab/evaluate.py fault-lab/run_scenario.py
pytest -q
python -m pip check
helm lint deploy/helm/kubemedic
```

项目完整测试共42个，覆盖Webhook、Incident去重与状态机、Evidence采集、规则Analyzer、DeepSeek Provider、Prompt预算、报告降级、周期一致性评分和实验运行结果组装。

## 构建与部署

```bash
podman build \
  -t docker.io/library/kubemedic:0.6.2 \
  .

podman save \
  --format docker-archive \
  -o /tmp/kubemedic-0.6.2.tar \
  docker.io/library/kubemedic:0.6.2

k3s ctr images import /tmp/kubemedic-0.6.2.tar

helm upgrade --install kubemedic deploy/helm/kubemedic \
  --namespace kubemedic \
  --force-conflicts \
  --wait \
  --timeout 5m
```

Helm部署使用非root用户、只读RBAC、RWO PVC、健康探针、ServiceMonitor，并配置`DEEPSEEK_MAX_TOKENS=2400`与`DEEPSEEK_THINKING_ENABLED=false`。

## API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/healthz` | 进程健康检查 |
| `GET` | `/readyz` | 服务就绪检查 |
| `GET` | `/metrics` | Prometheus指标 |
| `POST` | `/api/v1/alerts/webhook` | 接收Alertmanager Webhook |
| `GET` | `/api/v1/incidents` | 查询Incident列表 |
| `GET` | `/api/v1/incidents/{id}` | 查询Incident与状态时间线 |
| `GET` | `/api/v1/incidents/{id}/evidence` | 查询Evidence |
| `GET` | `/api/v1/incidents/{id}/analysis` | 查询Analyzer结果 |
| `GET` | `/api/v1/incidents/{id}/report` | 查询结构化RCA报告 |

详细的部署、故障实验、问题修复和验证证据记录在`docs/implementation-log.md`与项目实施文档中。
