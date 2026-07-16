# MCP 客户端接入

> 状态：Development preview  
> 最近核对：2026-07-16

## 当前限制

六个 MCP 工具已经实现，但 `pyproject.toml` 还没有正式的 `memory-workbench-mcp` 命令入口。当前只能使用开发命令启动 stdio server：

```bash
uv run python -c "from memory_workbench.mcp.server import run_stdio; run_stdio()"
```

下一阶段应把它固化为 package script，并用至少两个真实客户端完成安装验证。

## 通用客户端配置

不同客户端的配置文件位置不同，但 stdio 配置的核心信息相同：

```json
{
  "command": "uv",
  "args": [
    "run",
    "python",
    "-c",
    "from memory_workbench.mcp.server import run_stdio; run_stdio()"
  ],
  "cwd": "C:\\path\\to\\memory-tools"
}
```

Replace `cwd` with the absolute path of your local checkout.

客户端需要让 MCP 进程与 Web 服务使用同一个工作目录或同一个 `MW_DB_PATH`，否则它们会连接不同的 SQLite 文件。

## 六个工具

| 工具 | 行为 |
|---|---|
| `memory_propose` | 提议 candidate；必须声明 kind、scope、client_id |
| `memory_search` | 搜索 caller scope 可见的 active、有效期内记忆 |
| `memory_get` | 获取记忆详情、事件历史和相关读取记录 |
| `memory_correct` | 创建新 active 版本并 supersede 旧版本 |
| `memory_forget` | 逻辑 revoke；Agent 不能 hard purge |
| `memory_explain` | 解释记忆来源、历史和近期读取 |

## 最小调用约定

每个客户端使用稳定且可识别的 `client_id`，例如 `codex-local`、`claude-code-local` 或 `cursor-demo`。

调用 project scope 时同时提供 `project_id`：

```json
{
  "level": "project",
  "project_id": "memory-tools",
  "client_id": "codex-local"
}
```

不要让不同客户端为同一项目使用不同拼写，否则它们会进入不同 scope。

## 推荐验证流程

1. 启动 Web 服务并打开管理页。
2. 连接 Client A，调用 `memory_propose` 写入 project candidate。
3. 在 Web UI 中确认来源并点击 Approve。
4. 连接 Client B，使用相同 project ID 调用 `memory_search`。
5. 在 Web UI 查看 Trace。
6. Client A 或用户调用 `memory_correct`。
7. Client B 再次搜索，只应读到新版本。
8. 使用不同 project ID 搜索，应返回空结果。

## 权限规则

- MCP Agent 不能自动批准提议。
- MCP Agent 不能查询 revoked、quarantined 或 superseded 内容。
- MCP Agent 的 forget 是逻辑 revoke，不是 hard purge。
- hard purge 和重新批准属于本地用户管理面。
- scope 校验失败时，不应通过换 query 或提高 limit 绕过。

## 故障排查

### Client A 写入后 Client B 看不到

依次确认：

1. 两个进程使用同一个 `MW_DB_PATH` 或工作目录。
2. 记忆已经由用户批准为 active。
3. 两端的 level 和 project/workspace ID 完全一致。
4. 记忆没有过期、撤销或被 supersede。

### MCP 进程启动后立即退出

先在仓库目录手动运行开发命令，检查依赖安装和 Python 错误。当前尚无独立诊断命令。
