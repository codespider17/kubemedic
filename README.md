# KubeMedic

KubeMedic是一个面向Kubernetes告警的智能故障调查与评测项目。

## 当前阶段

M2：实现FastAPI健康检查和Alertmanager Webhook最小闭环。

## 安全边界

第一版只采集只读证据，不允许大模型执行Shell、kubectl或修改集群资源。

## 本地开发

项目目录：`/root/projects/kubemedic`

激活虚拟环境：`source /root/projects/kubemedic/.venv/bin/activate`
