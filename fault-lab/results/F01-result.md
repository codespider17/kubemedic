# F01 CrashLoopBackOff 实验结果

- 执行日期：2026-08-27
- 场景编号：F01
- 故障类型：CrashLoopBackOff
- 故障注入方式：向缓存的 node-exporter 镜像传入无效参数 `--kubemedic-invalid-flag`
- 主要分析 Incident：`inc-637b687d44274d57`
- 稳定性验证 Incident：`inc-4c4222abce6b4af0`
- 故障 Pod：`crashloop-demo-68c98b7975-sf7xc`、`crashloop-demo-68c98b7975-6hrt4`
- Prometheus 是否进入 firing：是
- Alertmanager receiver：`fault-lab/kubemedic/kubemedic-webhook`
- Evidence 总数：12
- Evidence 源：`pod_status`、`kubernetes_events`、`pod_logs`、`owner_chain`、`prometheus_query`
- Collector 错误数：0
- Analyzer 是否命中：是
- Analyzer：`crash_loop_backoff`
- 根因编码：`CONTAINER_CRASH_LOOP_BACKOFF`
- Analyzer 置信度：0.96
- DeepSeek 是否成功：是
- 模型：`deepseek-v4-flash`
- provider_error：无
- Token 数量：5176
- 推荐操作：修正无效启动参数；必要时回滚最近发布
- 推荐操作是否需要审批：是
- 抗抖动持续验证：954 秒
- 持续故障期间报告生成次数：1
- 持续故障期间错误 RESOLVED 次数：0
- 最终规则状态：`firing`
- 最终规则健康状态：`ok`
- KubeMedic 修复版本：`0.6.1`
- 自动化测试：27 个测试通过
- 最终恢复状态：`RESOLVED`

## 关键发现

最初使用瞬时 `CrashLoopBackOff` waiting-reason 指标时，容器重启瞬间会导致指标消失，Incident 曾发生错误恢复和重新打开。使用一分钟 `max_over_time` 后，仍无法覆盖 kubelet 超过一分钟的指数退避间隔。

最终规则采用两条归一化分支：精确的 `CrashLoopBackOff` waiting reason，或者“上一次异常退出、累计重启至少三次、当前未 Ready”的组合条件。规则使用 namespace、pod 和 container 聚合，消除了 reason、job 和 service 等动态标签对告警指纹的影响。

Incident Manager 原先未优先读取显式 workload 标签，并错误地将 Prometheus job 作为工作负载候选。修复后发布 `kubemedic:0.6.1`，通过单元测试、完整测试和容器内临时 SQLite 验证，确认 `workload=crashloop-demo` 优先于 `job=kube-state-metrics`。

## 验证边界

主要分析 Incident 完成了 Evidence、规则 Analyzer、DeepSeek 结构化报告和自动恢复闭环。稳定性 Incident 验证了最终复合规则在 954 秒内没有告警抖动或重复生成报告。

稳定性 Incident 创建后发生了 workload 指纹算法升级，升级前后的 fingerprint 不一致，导致该历史 Incident 无法自动关联 resolved 回调。在确认健康 Pod、Prometheus 和 Alertmanager 均恢复后，通过 `transition_incident()` 状态机服务完成一次性人工协调，并写入明确审计事件。该次人工协调不得表述为自动恢复成功。
