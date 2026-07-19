# 当前进度

> 文档状态：Active
> 最近核对：2026-07-19
> 适用版本：0.2.x cross-tool onboarding

项目阶段：Cross-tool onboarding。生产就绪：否（本地试用就绪）。

## 一句话结论

跨工具 MCP 接入闭环已落地：`memory-workbench-mcp` 已封装为 console script，端点身份绑定到 `MW_CLIENT_ID`，端点活动通过 observation 表推导状态，Web UI 端点卡片可以一键生成 Codex / Claude / Cursor 配置。下一步应推进 Alembic 迁移与 FTS5。

## 已完成

- Python 3.12 + FastAPI + SQLAlchemy + SQLite 本地服务。
- `MemoryEvent` 事件账本与 `MemoryRecord` 当前投影。
- `candidate / active / superseded / quarantined / revoked` 生命周期。
- global、workspace、project、agent、session 五级 scope 可见性矩阵。
- 六个 MCP 工具：propose、search、get、correct、forget、explain。
- HTTP 管理接口 + React + TypeScript + Vite Web UI（Inbox / Explorer / Memory Routing / Endpoints / Traces）。
- 默认只检索 active 且处于有效期内的记忆。
- 检索 Trace 持久化，查询内容默认以摘要形式脱敏。
- 凭据模式拒写、跨 scope 纠错拒绝、purge 内容擦除。
- 投影删除后可从事件重建。
- `memory-workbench-mcp` console script 已注册（`mcp/entrypoint.py`），只启动 stdio server，不启动 Uvicorn。
- 纯函数 MCP 配置渲染器（Codex / Claude / Cursor；installed 与 repository profile）。
- 端点 observation 表（`endpoint_observations`），状态派生为 `never_seen | active | stale`（24h 阈值）。
- 仅成功的 MCP 工具调用写入脱敏 observation；从不存查询文本或记忆正文。
- `MW_CLIENT_ID` 是权威 caller 标识；工具参数与之一致或冲突被拒绝。
- HTTP `GET /endpoints/{id}/status` 与 `POST /endpoints/{id}/setup`；AssetDetailOut 包含端点状态字段。
- React 端点卡片 + setup drawer，支持 Copy 与 Download，不自动写入 IDE 配置。
- 102 个 pytest 测试通过；`npm run build` 干净通过。

## 部分完成

| 能力 | 当前状态 | 缺口 |
|---|---|---|
| MCP 接入 | console script + 渲染器 + observation + stdio 启动 smoke test | 未做 Codex/Cursor/Claude 真实安装验证 |
| Web 管理 | React UI 覆盖资产、端点、项目、记忆路由 | 缺 Inbox/Conflicts/Settings 完整视图；端点 setup 无 Vitest/Playwright |
| 检索 | scope、状态、有效期、子串匹配、稳定排序 | 尚无 SQLite FTS5、token budget 和 10k 数据性能验证 |
| 冲突处理 | Repository 有结构化匹配基础 | 尚无冲突审议流程与页面 |
| 数据生命周期 | approve/quarantine/revoke/purge 已实现 | UI 尚未暴露全部管理操作；管理接口仍依赖 loopback 信任模型 |
| 数据库演进 | `create_all` 可初始化（包括新增 observation 表） | 尚无 Alembic 迁移 |

## 尚未开始

- JSONL 导入导出与兼容性检查。
- FTS5 索引、检索基准和分页。
- Vitest 与 Playwright 端到端测试。
- 安装向导（首次运行生成 MCP 配置片段）。
- Memory Linter（Secret / PII / 过期 / 跨 scope 规则）。
- 远程访问认证、团队权限和跨设备同步（MVP 非目标）。
- Security Lab 集成（MVP 非目标）。

## 推荐下一步

1. 用至少两个真实 MCP 客户端完成端到端验收清单（见 `docs/mcp-client-guide.md`）。
2. 引入 Alembic，固定 schema 演进方式；`endpoint_observations` 作为基线迁移的一部分。
3. 实现 FTS5，并用 10k 短记忆验证 p95 小于 200ms。
4. 为 setup drawer 与端点卡片补 Vitest 单元测试与 Playwright 用例。
5. 增加 Inbox / Conflicts / Settings 页面。

每完成一项，需要同步更新本页、相关技术文档、使用说明和测试结果。

# AgentAsset milestone addendum (2026-07-16)

The 0.1.x tracer-bullet now includes a React + TypeScript + Vite management
UI, backed by Python/FastAPI. AgentAsset, AgentEndpoint, ProjectMembership,
and MemoryGrant are implemented and covered by integration tests. A bound
endpoint's searches use the asset's effective active-memory set; unbound
clients retain strict scope-only retrieval. Explicit grants can be revoked and
never copy memory content or event history.

# Cross-tool onboarding milestone addendum (2026-07-19)

The 0.2.x milestone adds:

- `memory-workbench-mcp` packaged console script (stdio only, no Uvicorn).
- Pure MCP config renderers for Codex / Claude / Cursor with installed and
  repository launch profiles.
- `MW_CLIENT_ID`-authoritative caller identity; tool argument conflicts
  rejected with `ClientMismatch` (`VALIDATION`).
- `EndpointObservationRow` + observation repository + status derivation
  (`never_seen | active | stale`); 24h stale threshold.
- HTTP `GET /endpoints/{id}/status` and `POST /endpoints/{id}/setup`;
  AssetDetailOut includes the same status fields.
- React EndpointCard with status pill, last activity, visible memory
  count, launch profile selector, and a setup drawer that renders the
  generated JSON as text and offers Copy / Download. The UI never writes
  IDE config files automatically.

Still deferred: real two-client install verification, Alembic migration for
the new table, and FTS5 search.
