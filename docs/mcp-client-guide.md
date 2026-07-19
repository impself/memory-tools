# MCP 客户端接入

> 文档状态：Current
> 最近核对：2026-07-19
> 适用版本：0.2.x cross-tool onboarding

## 概览

Memory Workbench 通过本地 MCP stdio server 暴露六个工具。每个客户端需要：

1. 一个已安装的 `memory-workbench-mcp` 命令，或仓库内的 `uv run memory-workbench-mcp` 开发命令。
2. 一个稳定 `client_id`，例如 `codex-local`、`claude-code-local`、`cursor-demo`。
3. 同一份 SQLite 数据库：Web 服务和所有 MCP 进程必须使用同一个 `MW_DB_PATH` 或同一个工作目录。

`MW_CLIENT_ID` 是权威 caller 标识。工具参数里的 `client_id` 仅作为兼容字段保留；当两者都存在且不一致时，MCP server 会返回 `VALIDATION` 错误。这防止 LLM 假冒其它客户端身份。

## 安装与启动

### 已安装命令

```bash
uv tool install memory-workbench
memory-workbench-mcp
```

`memory-workbench-mcp` 只启动 stdio MCP server，不会启动 FastAPI / Uvicorn。

在仓库根目录运行 `make mcp-check` 会同时确认 console script 已注册，并启动一次短暂的 stdio server smoke test。

### 仓库内开发命令

```bash
uv sync --extra dev
uv run memory-workbench-mcp
```

如果希望同时运行 Web 服务，使用另一个进程：

```bash
uv run memory-workbench
```

## 客户端配置片段

使用 Web UI 端点卡片中的「生成配置」按钮可得到粘贴即用的 JSON。下面是 Codex、Claude、Cursor 三种平台的最小示例。

所有片段都把 `MW_CLIENT_ID` 设为端点的稳定 client id；可选 `MW_DB_PATH` 必须使用绝对路径，相对路径会被拒绝。

### Codex

```json
{
  "mcpServers": {
    "memory-workbench": {
      "command": "memory-workbench-mcp",
      "args": [],
      "env": {
        "MW_CLIENT_ID": "codex-local",
        "MW_DB_PATH": "/absolute/path/to/memory.db"
      }
    }
  }
}
```

### Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "memory-workbench": {
      "command": "memory-workbench-mcp",
      "args": [],
      "env": {
        "MW_CLIENT_ID": "claude-code-local",
        "MW_DB_PATH": "/absolute/path/to/memory.db"
      }
    }
  }
}
```

### Cursor

```json
{
  "mcpServers": {
    "memory-workbench": {
      "command": "memory-workbench-mcp",
      "args": [],
      "env": {
        "MW_CLIENT_ID": "cursor-demo",
        "MW_DB_PATH": "/absolute/path/to/memory.db"
      }
    }
  }
}
```

仓库内开发模式把 `command` 替换为 `uv`，并加上 `--directory <repo>` 与 `run memory-workbench-mcp`：

```json
{
  "mcpServers": {
    "memory-workbench": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/memory-tools",
        "run",
        "memory-workbench-mcp"
      ],
      "env": {
        "MW_CLIENT_ID": "codex-local"
      }
    }
  }
}
```

具体客户端配置文件位置以各客户端官方文档为准；不要让本工具自动写入 IDE 配置。

## 六个工具

| 工具 | 行为 |
|---|---|
| `memory_propose` | 提议 candidate；必须声明 kind、scope |
| `memory_search` | 搜索 caller scope 可见的 active、有效期内记忆 |
| `memory_get` | 获取记忆详情、事件历史和相关读取记录 |
| `memory_correct` | 创建新 active 版本并 supersede 旧版本 |
| `memory_forget` | 逻辑 revoke；Agent 不能 hard purge |
| `memory_explain` | 解释记忆来源、历史和近期读取 |

## 端点状态语义

Web UI 的端点卡片使用三种状态：

| 状态 | 含义 |
|---|---|
| `never_seen` | 端点已绑定，但还没有任何成功的 MCP 调用 |
| `active` | 最近 24 小时内有成功的 MCP 调用 |
| `stale` | 最后一次成功调用已经超过 24 小时 |

状态只来源于本地 MCP server 记录的 observation，**不**做网络健康探测，也不声称 IDE 是否在线。

`automatic` 同步模式只是元数据：它不会让记忆被静默注入到 prompt，仍然需要客户端主动调用 `memory_search`。未来 delivery 机制会单独引入。

## 验证流程：两个客户端共享记忆

1. 在 Web UI 创建一个 AgentAsset，并为每个客户端添加 endpoint。
2. 在 Web UI 通过「生成配置」得到 Codex 与 Claude/Cursor 的 JSON，分别粘贴到对应客户端配置。
3. 启动 Web 服务，确保 `MW_DB_PATH` 与客户端配置一致。
4. Client A 调用 `memory_propose`，写入 project candidate。
5. 在 Web UI Inbox 中批准该记忆。
6. Client B 使用相同 project ID 调用 `memory_search`，应看到记忆。
7. 使用不同 project ID 搜索，应返回空。
8. 在 Web UI 撤销记忆，Client B 再次搜索应不再返回。
9. 检查 Traces 页面，确认每次搜索都归属正确的 AgentAsset。

## 权限规则

- MCP Agent 不能自动批准提议。
- MCP Agent 不能查询 revoked、quarantined 或 superseded 内容。
- MCP Agent 的 forget 是逻辑 revoke，不是 hard purge。
- `approved` 与 `purged` 事件只能由本地用户管理面发起。
- scope 校验失败时，不应通过换 query 或提高 limit 绕过。

## 故障排查

### `VALIDATION` 错误：client_id 冲突

工具参数 `client_id` 与环境变量 `MW_CLIENT_ID` 不一致。统一使用 `MW_CLIENT_ID`，移除工具参数。

### Client A 写入后 Client B 看不到

依次确认：

1. 两个进程使用同一个 `MW_DB_PATH` 或工作目录。
2. 记忆已经由用户批准为 active。
3. 两端的 level 和 project/workspace ID 完全一致。
4. 记忆没有过期、撤销或被 supersede。
5. Client B 已被绑定到能看见该 scope 的 AgentAsset。

### MCP 进程启动后立即退出

在仓库目录手动运行 `uv run memory-workbench-mcp`，检查 stderr 输出。常见原因：数据库路径不可写、Python 版本低于 3.12、未执行 `uv sync`。

### 状态长时间停在 `never_seen`

端点已绑定但 MCP 进程从未运行过成功调用。检查客户端配置是否被加载、`MW_CLIENT_ID` 是否与端点一致、客户端是否真的调用了任何 memory_* 工具。
