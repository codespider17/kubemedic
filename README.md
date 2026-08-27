# KubeMedic

基于 Kubernetes、Prometheus、Alertmanager 与 DeepSeek API 的证据驱动智能故障调查平台。

KubeMedic 不只是把错误日志转发给大模型。系统会接收真实告警、完成 Incident 去重与状态流转、从 Kubernetes 和 Prometheus 采集证据、运行确定性规则 Analyzer，再由 DeepSeek 生成结构化根因分析报告。告警恢复后，同一个 Incident 会自动更新为 `RESOLVED`。

## 当前状态

当前已完成 M9：K3s 真实告警闭环、Helm 部署和 F01 CrashLoopBackOff 故障注入评测。

已验证链路：

```text
PrometheusRule
  -> Prometheus firing
  -> Alertmanager 路由
  -> KubeMedic Webhook
  -> Incident 去重与状态机
  -> Kubernetes / Prometheus 证据采集
  -> 规则 Analyzer
  -> DeepSeek 结构化报告
  -> REPORTED
  -> Alertmanager resolved Webhook
  -> RESOLVED
```

已完成一次真实集群验证：测试告警成功进入 `firing`，Alertmanager 匹配 `demo/kubemedic/kubemedic-webhook`，Incident 自动进入 `REPORTED`，告警恢复后进入 `RESOLVED`；重建 KubeMedic Pod 后 Incident 与报告仍可查询，SQLite PVC 持久化有效。

## 核心能力

- 接收 Alertmanager Webhook，并根据告警指纹完成 Incident 去重。
- 使用 `RECEIVED`、`COLLECTING`、`ANALYZING`、`REPORTED`、`RESOLVED` 等状态记录故障生命周期。
- 从 Kubernetes 采集 Pod、Deployment、Service、EndpointSlice、Events 和容器日志。
- 使用预定义 PromQL 查询采集重启次数、资源状态等指标，拒绝模型生成任意 PromQL。
- 内置 6 条确定性 Analyzer，对常见 Kubernetes 故障进行可解释匹配。
- 调用 DeepSeek API 输出结构化 RCA 报告，并在模型不可用时保留规则降级能力。
- 使用 SQLite 保存 Incident、Evidence、Analyzer 结果和报告。
- 提供健康检查、就绪检查和 Prometheus `/metrics` 接口。
- 使用 Helm 部署，配置只读 RBAC、Secret、ServiceMonitor 和 RWO PVC。
- 应用容器以非 root 用户运行，不允许读取 Secret 或删除 Pod。

## 内置规则 Analyzer

| Analyzer | 识别场景 |
| --- | --- |
| `oom_killed` | 容器因内存不足被终止 |
| `crash_loop_backoff` | 容器反复启动失败 |
| `image_pull` | 镜像拉取或鉴权失败 |
| `probe_failure` | 存活或就绪探针失败 |
| `pending_scheduling` | Pod 无法完成调度 |
| `service_no_endpoints` | Service 没有可用后端端点 |

规则 Analyzer 负责提供确定性判断和证据锚点，DeepSeek 负责综合证据、解释可能根因并生成排查建议。两者不是互相替代关系。

## 技术栈

- Kubernetes：K3s
- 监控告警：Prometheus、Alertmanager、kube-prometheus-stack
- 后端：Python、FastAPI、Pydantic
- Kubernetes 客户端：Kubernetes Python Client
- 数据库：SQLite + PVC
- 大模型：DeepSeek API
- 指标：prometheus-client
- 部署：Helm、Podman、containerd
- 质量检查：pytest、Ruff、pip check、helm lint

## 项目结构

```text
kubemedic/
├── app/
│   ├── analyzers/          # 规则 Analyzer 与执行引擎
│   ├── api/                # Alert、Incident、Evidence、Report API
│   ├── collectors/         # Kubernetes 与 Prometheus 证据采集
│   ├── domain/             # Incident、Evidence、Analysis、Report 模型
│   ├── providers/          # DeepSeek Provider
│   ├── repositories/       # SQLite 数据访问
│   ├── services/           # Incident、Evidence、Analysis、Report 流程
│   ├── tools/              # 后续受控工具调用扩展点
│   └── main.py             # FastAPI 入口和观测端点
├── deploy/
│   ├── alertmanager/       # AlertmanagerConfig 与测试规则
│   ├── demo-app/           # 演示工作负载
│   ├── helm/kubemedic/     # KubeMedic Helm Chart
│   ├── rbac/               # 只读 RBAC 基线
│   └── monitoring-values.yaml
├── fault-lab/
│   ├── base/               # 实验命名空间和告警路由
│   ├── scenarios/          # 可复现故障注入与恢复配置
│   └── results/            # 脱敏后的实验结果
├── docs/
│   └── implementation-log.md
├── tests/
├── Dockerfile
├── pyproject.toml
└── README.md
```

## 本地开发

要求：Python 3.12 或更高版本。

```bash
git clone git@github.com:codespider17/kubemedic.git
cd kubemedic

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
```

运行质量检查：

```bash
ruff check app tests
pytest -q
python -m pip check
```

启动开发服务：

```bash
export KUBEMEDIC_AUTO_PIPELINE=false
uvicorn app.main:app --host 127.0.0.1 --port 5001
```

## 容器构建与 K3s 导入

```bash
podman build \
  -t docker.io/library/kubemedic:0.6.1 \
  .

podman save \
  --format docker-archive \
  -o /tmp/kubemedic-0.6.1.tar \
  docker.io/library/kubemedic:0.6.1

k3s ctr images import /tmp/kubemedic-0.6.1.tar

k3s ctr images list |
  grep 'docker.io/library/kubemedic:0.6.1'
```

该方式适合无法稳定访问 Docker Hub 的本地实验环境。Helm Chart 使用 `IfNotPresent`，优先使用已经导入 K3s containerd 的镜像。

## Helm 部署

创建命名空间：

```bash
kubectl create namespace kubemedic \
  --dry-run=client \
  -o yaml |
kubectl apply -f -
```

安全创建 DeepSeek Secret，不要把 API Key 写入 Git：

```bash
read -rsp 'DeepSeek API Key: ' DEEPSEEK_API_KEY
echo

kubectl -n kubemedic create secret generic deepseek-api \
  --from-literal=api-key="$DEEPSEEK_API_KEY" \
  --dry-run=client \
  -o yaml |
kubectl apply -f -

unset DEEPSEEK_API_KEY
```

部署：

```bash
helm upgrade --install kubemedic deploy/helm/kubemedic \
  --namespace kubemedic \
  --force-conflicts \
  --wait \
  --timeout 5m
```

`--force-conflicts`只用于把本项目早期由 `kubectl apply` 创建的 `kubemedic-readonly` RBAC 字段迁移给 Helm 管理，不应随意用于共享资源。

验证：

```bash
helm status kubemedic -n kubemedic
kubectl -n kubemedic get deploy,pod,svc,pvc,servicemonitor
kubectl -n kubemedic logs deployment/kubemedic --tail=100
```

## API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/healthz` | 进程健康检查 |
| `GET` | `/readyz` | 数据库和服务就绪检查 |
| `GET` | `/metrics` | Prometheus 指标 |
| `POST` | `/api/v1/alerts/webhook` | 接收 Alertmanager Webhook |
| `GET` | `/api/v1/incidents` | 查询 Incident 列表 |
| `GET` | `/api/v1/incidents/{id}` | 查询 Incident 详情 |
| `GET` | `/api/v1/incidents/{id}/evidence` | 查询证据 |
| `GET` | `/api/v1/incidents/{id}/analysis` | 查询 Analyzer 结果 |
| `GET` | `/api/v1/incidents/{id}/report` | 查询结构化报告 |

端口转发后可以访问 OpenAPI：

```bash
kubectl -n kubemedic port-forward service/kubemedic 5001:5001
```

浏览器打开：`http://127.0.0.1:5001/docs`。

## 安全边界

- DeepSeek API Key 仅通过 Kubernetes Secret 注入，不进入镜像、数据库和 Git。
- KubeMedic ServiceAccount 只读取故障调查需要的 Kubernetes 资源。
- 当前版本不能读取 Kubernetes Secret，也不能删除 Pod。
- Prometheus 查询使用预定义 `query_id`，不执行模型生成的任意 PromQL。
- 当前版本只生成诊断报告，不允许大模型直接执行修复命令。
- SQLite 数据目录位于 PVC，Deployment 固定单副本并使用 `Recreate` 策略。

## 已验证结果

- K3s 节点、Prometheus、Alertmanager 和 KubeMedic Pod 正常运行。
- AlertmanagerConfig 被实际运行配置加载。
- 测试告警成功从 Prometheus 进入 Alertmanager。
- Alertmanager 成功调用集群内 KubeMedic Webhook。
- Incident 自动从 `RECEIVED` 流转到 `REPORTED`。
- 告警恢复后，同一 Incident 自动变为 `RESOLVED`。
- KubeMedic Pod 重建后，Incident 和报告仍然存在。
- Ruff 检查通过，27 个 pytest 全部通过，pip check 与 Helm lint 均通过。

详细的每次实施证据记录在 `docs/implementation-log.md`。

## 当前限制

- 当前是面向学习、演示和故障实验的单节点 K3s 版本，不宣称生产级高可用。
- SQLite + RWO PVC 模式固定单副本，不支持水平扩展。
- 当前已完成 F01 CrashLoopBackOff，OOMKilled、ImagePullBackOff、探针失败、调度失败和 Service 无 Endpoint 场景仍待验证。
- 当前不允许模型直接执行运维命令。

## Roadmap

- [x] Alertmanager Webhook 与 Incident 状态机
- [x] SQLite 持久化与告警去重
- [x] Kubernetes、日志和 Prometheus 证据采集
- [x] 6 条规则 Analyzer
- [x] DeepSeek 结构化 RCA 与规则降级
- [x] Helm、只读 RBAC、PVC 和 ServiceMonitor
- [x] `FIRING -> REPORTED -> RESOLVED` 自动闭环
- [ ] 受控多轮工具调用与人工确认
- [x] CrashLoopBackOff 故障注入、根因分析与恢复验证
- [ ] OOMKilled、ImagePullBackOff 等故障注入
- [ ] Top-1、Top-3、耗时和 Token 成本评测
- [ ] Runbook 知识库与相似案例检索

## M9：CrashLoopBackOff 故障注入评测

已完成 F01 CrashLoopBackOff 真实故障注入和分阶段闭环验证，包括 Prometheus/Alertmanager 告警链路、12 条多源 Evidence、规则 Analyzer 精确根因、DeepSeek 结构化报告、审批型修复建议以及恢复状态验证。

针对 kubelet 指数退避造成的 waiting-reason 指标抖动，告警规则采用精确状态与“异常退出、重启次数、Ready 状态”的复合条件，并归一化动态标签。最终规则持续验证 954 秒，期间未发生错误恢复或重复报告。

修复 Incident workload 标签映射问题并发布 `kubemedic:0.6.1`，完整测试共 27 个。详细证据见 `fault-lab/results/F01-result.md`。
