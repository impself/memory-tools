# Memory Workbench MVP 规格 v0.1

> 文档状态：Frozen baseline
> 最近核对：2026-07-16
> 适用版本：本地单用户 MVP v0.1

## 1. 产品目标

为多个本地 AI 客户端提供同一套可审计、可纠错、按 scope 隔离的长期记忆。用户拥有批准、审议和彻底删除的最终控制权。

## 2. 核心价值

- 不静默覆盖：每次变化都有事件和版本关系。
- 不跨项目泄露：scope 在任何排序或语义检索之前执行。
- 不让 Agent 自我授权：Agent 可以提议和逻辑忘记，不能批准或 hard purge。
- 可解释：可以查看记忆来源、事件历史和读取记录，但不宣称 Trace 能证明 Agent 行为因果。
- 本地优先：默认不需要云账号、外部模型或 API key。

## 3. MVP 范围

### 必须具备

- SQLite 事件账本、当前投影和确定性重放。
- 五级 scope 与跨客户端共享。
- 六个 MCP 工具。
- candidate、active、superseded、quarantined、revoked 生命周期。
- 用户管理 UI：至少可查看、批准、搜索、纠错和查看 Trace。
- active + 有效期默认过滤。
- secret 拒写、Trace 默认脱敏和 hard purge。
- JSONL 导入导出。
- FTS5 检索和基础性能验证。
- 单进程安装与首次使用闭环。

### 明确不做

- 云账号、跨设备同步、团队 RBAC/SSO。
- 知识图谱依赖和自建 embedding/reranker。
- 静默捕获全部对话。
- 可靠的自由文本自动冲突裁决。
- 严格反事实回放和审计报告。

## 4. 硬性规则

1. 事件身份和历史不可变；hard purge 只允许破坏性擦除 payload 内容字段。
2. scope-before-rank，任何检索实现都不能改变这一顺序。
3. 删除投影并重放事件必须恢复所有非 purged 记录。
4. purge 删除内容和索引并留下无内容 tombstone。
5. 默认只绑定 `127.0.0.1`；远程绑定前必须增加认证和警告。
6. 日志与 Trace 默认不保存完整记忆内容或原始敏感 query。
7. 只有结构化 `subject + predicate + scope` 可以自动进入冲突候选。
8. Agent 不能直接批准或 hard purge。
9. 对外行为、安装方式或架构改变时，文档与代码必须在同一提交更新。

## 5. 验收标准

- Client A 写入 project candidate，用户批准后，Client B 在相同 project 中可检索。
- 不同 project ID 默认不可见。
- 纠错创建新 ID，旧记录变为 superseded，默认搜索只返回新版本。
- revoked、superseded、quarantined、未生效和过期记录不出现在 Agent 默认搜索中。
- 每次成功搜索写入一条脱敏 RetrievalTrace。
- 投影重建结果与在线状态一致，purged 内容不会复活。
- JSONL 往返保留非 purged 状态和关系。
- 10k 短记忆 FTS p95 小于 200ms，不包含外部模型调用。
- 用户在 10 分钟内完成安装、连接两个客户端、共享并纠错一条记忆。
- 核心 UI 在 375px 和 1280px 宽度可用。

## 6. 当前偏差

截至 2026-07-16，核心 tracer-bullet 已实现，但以下 MVP 条目尚未满足：

- JSONL 导入导出。
- FTS5 与 10k 性能验收。
- 正式 MCP CLI 和真实双客户端安装验收。
- React + TypeScript 管理 UI 与响应式 E2E 验收。
- Alembic schema 迁移。

当前状态以 [status.md](status.md) 为准。
