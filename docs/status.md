# 当前进度

> 文档状态：Active
> 最近核对：2026-07-16
> 适用版本：0.1.x tracer-bullet

项目阶段：Tracer-bullet。生产就绪：否。

## 一句话结论

核心链路已经跑通：记忆提议、用户批准、按 scope 检索、Trace 记录、纠错版本化、撤销和投影重放均有实现与测试；下一步应优先完成 MCP 安装闭环和正式检索能力，而不是继续扩张功能面。

## 已完成

- Python 3.12 + FastAPI + SQLAlchemy + SQLite 本地服务。
- `MemoryEvent` 事件账本与 `MemoryRecord` 当前投影。
- `candidate / active / superseded / quarantined / revoked` 生命周期。
- global、workspace、project、agent、session 五级 scope 可见性矩阵。
- 六个 MCP 工具：propose、search、get、correct、forget、explain。
- HTTP 管理接口和随 FastAPI 提供的最小 Web UI。
- 默认只检索 active 且处于有效期内的记忆。
- 检索 Trace 持久化，查询内容默认以摘要形式脱敏。
- 凭据模式拒写、跨 scope 纠错拒绝、purge 内容擦除。
- 投影删除后可从事件重建。
- 63 个 pytest 测试；Ruff 与源码 mypy 检查通过。

## 部分完成

| 能力 | 当前状态 | 缺口 |
|---|---|---|
| MCP 接入 | 六个工具已实现 | 尚无正式 MCP CLI 入口；缺少真实双客户端安装验证 |
| Web 管理 | 可提议、批准、搜索、纠错、查看 Trace | 仍是单文件 HTML/JS，不是目标中的 React + TypeScript；缺少 Inbox/Conflicts/Settings |
| 检索 | scope、状态、有效期、子串匹配、稳定排序 | 尚无 SQLite FTS5、token budget 和 10k 数据性能验证 |
| 冲突处理 | Repository 有结构化匹配基础 | 尚无冲突审议流程与页面 |
| 数据生命周期 | approve/quarantine/revoke/purge 已实现 | Web UI 尚未暴露全部管理操作；管理接口仍依赖 loopback 信任模型 |
| 数据库演进 | `create_all` 可初始化 | 尚无 Alembic 迁移 |

## 尚未开始

- JSONL 导入导出与兼容性检查。
- FTS5 索引、检索基准和分页。
- React + TypeScript + Vite 前端工程。
- OpenAPI TypeScript 客户端生成。
- Vitest 与 Playwright 端到端测试。
- 安装向导、客户端配置生成和诊断命令。
- 远程访问认证、团队权限和跨设备同步（MVP 非目标）。

## 推荐下一步

1. 增加 `memory-workbench-mcp` 正式入口，完成 Codex + 第二客户端的真实连接测试。
2. 写 MCP 安装诊断和第一条记忆的 10 分钟上手闭环。
3. 引入 Alembic，固定 schema 演进方式。
4. 实现 FTS5，并用 10k 短记忆验证 p95 小于 200ms。
5. 再建立 React + TypeScript 前端，优先 Inbox、Explorer、Trace 三个页面。

每完成一项，需要同步更新本页、相关技术文档、使用说明和测试结果。
