# 使用说明

> 文档状态：Active
> 最近核对：2026-07-16
> 适用版本：0.1.x tracer-bullet

## 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Windows、macOS 或 Linux 本地环境

## 安装

在仓库根目录执行：

```bash
uv sync --extra dev
```

## 启动 Web 服务

```bash
uv run memory-workbench
```

打开：`http://127.0.0.1:8000`

首次启动会在当前目录创建 `memory_workbench.db`。如需指定位置：

```powershell
$env:MW_DB_PATH = "D:\data\memory-workbench.db"
uv run memory-workbench
```

不要直接把服务绑定到公网。当前管理接口没有远程访问认证。

## 完成第一条记忆

1. 在 Propose 区域填写内容，例如 `Demo project uses pnpm`。
2. 选择 kind，并使用 project scope 填写项目 ID，例如 `demo`。
3. 点击 **Propose candidate**。
4. 在 Memories 列表找到 candidate，点击 **Approve**。
5. 在 Search 区域使用相同 project ID 搜索 `pnpm`。
6. 搜索结果出现后，右侧 Recent Traces 会显示脱敏后的检索记录。
7. 点击记忆的 **Correct**，输入新内容；旧版本会变为 superseded，新版本保持 active。

## Scope 怎么选

| Scope | 用途 | 必填 ID |
|---|---|---|
| global | 所有上下文都可使用的通用规则 | 无 |
| workspace | 某个工作区共享 | `workspace_id` |
| project | 某个项目共享 | `project_id` |
| agent | 某个 Agent 专用 | `agent_id` |
| session | 某次会话临时使用 | `session_id` |

project、agent、session 可以同时携带更宽层级的父 ID。搜索时要提供足够的父级上下文，否则更宽层级但带父 ID 的记录可能不可见。

## HTTP 示例

### 提议 candidate

```bash
curl -X POST http://127.0.0.1:8000/api/memories \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Demo project uses pnpm",
    "kind": "preference",
    "scope": {"level": "project", "project_id": "demo"},
    "client_id": "manual-client"
  }'
```

记下响应中的 `id`。提议默认是 candidate，`auto_approve` 会被接口拒绝。

### 用户批准

```bash
curl -X POST http://127.0.0.1:8000/api/memories/MEMORY_ID/approve \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 搜索

```bash
curl -X POST http://127.0.0.1:8000/api/memories/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "pnpm",
    "scope": {"level": "project", "project_id": "demo"},
    "client_id": "manual-client",
    "limit": 20
  }'
```

搜索只返回 active 且处于有效期内的记录。不同 project ID 不会看到这条记忆。

### 健康检查

```bash
curl http://127.0.0.1:8000/api/health
```

## 开发检查

```bash
uv run pytest
uv run ruff check .
uv run mypy src/memory_workbench
```

当前基线：63 个测试通过，Ruff 与源码 mypy 通过。

## 常见问题

### 搜索不到刚提议的记忆

candidate 不会被默认搜索返回。请先在 Web UI 中批准，并确认搜索 scope 与写入 scope 一致。

### 为什么 Trace 不显示原始查询

为了避免日志泄露隐私和凭据，Trace 只保存 query 的 hash/长度摘要。搜索本身仍使用本次请求的原始 query。

### 可以恢复被纠错的旧版本吗

旧版本仍保留为 superseded，可在管理列表和事件历史中检查，但默认搜索不会返回。

### 数据库 schema 需要升级怎么办

当前版本尚未引入 Alembic。升级前先备份 `memory_workbench.db`；涉及 schema 变化时以发布说明为准。
# AgentAsset workflow addendum (2026-07-16)

After `uv run memory-workbench`, install the TypeScript UI once with
`cd frontend; npm install`, then use `npm run dev` for development or
`npm run build` to update the FastAPI-served production bundle. Create an
AgentAsset, associate a Project, bind a unique client id, and grant selected
active memories. Clicking a project filters its memory view; Correct creates a
new canonical version and Revoke removes an explicit grant.
