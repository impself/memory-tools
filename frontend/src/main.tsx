import { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api";
import type {
  Asset,
  Endpoint,
  EndpointSetupResponse,
  EndpointStatus,
  LaunchProfile,
  Memory,
  Project,
  SyncMode,
} from "./types";
import "./styles.css";

type Notice = { tone: "error" | "ok"; text: string } | null;
const syncLabel: Record<SyncMode, string> = { manual: "手动同步", automatic: "自动同步" };
const statusLabel: Record<EndpointStatus, string> = {
  never_seen: "未观测",
  active: "近 24 小时活跃",
  stale: "超过 24 小时未观测",
};
const statusHint: Record<EndpointStatus, string> = {
  never_seen: "端点已绑定，但还没有任何 MCP 工具调用过它。",
  active: "最近 24 小时内有成功的 MCP 调用。",
  stale: "最后一次调用已经超过 24 小时，请确认客户端仍在使用。",
};

function App() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<Notice>(null);
  const selected = useMemo(() => assets.find((asset) => asset.id === selectedId) ?? assets[0] ?? null, [assets, selectedId]);

  async function refresh(preferredId?: string) {
    setLoading(true);
    try {
      const [nextAssets, nextProjects, nextMemories] = await Promise.all([api.assets(), api.projects(), api.memories()]);
      setAssets(nextAssets); setProjects(nextProjects); setMemories(nextMemories);
      setSelectedId(preferredId ?? selectedId ?? nextAssets[0]?.id ?? null);
    } catch (error) { setNotice({ tone: "error", text: error instanceof Error ? error.message : "加载失败" }); }
    finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, []);
  async function act(action: () => Promise<unknown>, success: string) {
    try { await action(); setNotice({ tone: "ok", text: success }); await refresh(selected?.id); }
    catch (error) { setNotice({ tone: "error", text: error instanceof Error ? error.message : "操作失败" }); }
  }

  return <main className="shell">
    <header className="masthead"><div><p className="eyebrow">LOCAL-FIRST / CONTROL PLANE</p><h1>Memory <em>Workbench</em></h1></div><div className="mast-stat"><b>{assets.length}</b><span>Agent 资产</span></div><div className="mast-stat"><b>{memories.length}</b><span>可用记忆</span></div><button className="refresh" onClick={() => void refresh()} disabled={loading}>重新同步视图</button></header>
    {notice && <div className={`notice ${notice.tone}`}>{notice.text}<button onClick={() => setNotice(null)}>×</button></div>}
    <section className="deck">
      <aside className="assets-panel panel"><div className="panel-head"><span>01</span><h2>Agent Assets</h2></div><AssetForm onSubmit={(body) => act(async () => { const asset = await api.createAsset(body); setSelectedId(asset.id); }, "已创建 Agent 资产")} /><div className="asset-list">{assets.map((asset, index) => <button key={asset.id} className={`asset-card ${selected?.id === asset.id ? "selected" : ""}`} onClick={() => setSelectedId(asset.id)}><span className="asset-index">0{index + 1}</span><strong>{asset.name}</strong><small>{asset.role_tags.join(" · ") || "未定义角色"}</small><footer><span>{asset.projects.length} 项目</span><span>{asset.memory_count} 记忆</span></footer></button>)}{!loading && assets.length === 0 && <Empty text="先创建一个稳定的 Agent 资产。" />}</div></aside>
      <section className="detail-panel panel"><div className="panel-head"><span>02</span><h2>Asset Ledger</h2></div>{selected ? <AssetLedger asset={selected} projects={projects} selectedProjectId={selectedProjectId} onSelectProject={setSelectedProjectId} onAct={act} /> : <Empty text="选择或创建资产后，项目、端点和记忆关系会在这里展开。" />}</section>
      <aside className="memory-panel panel"><div className="panel-head"><span>03</span><h2>Memory Routing</h2></div>{selected ? <MemoryRouting asset={selected} allMemories={memories} selectedProjectId={selectedProjectId} onAct={act} /> : <Empty text="资产建立后，可以将单条记忆显式路由给它。" />}</aside>
    </section>
  </main>;
}

function AssetForm({ onSubmit }: { onSubmit: (body: { name: string; role_tags: string[]; default_sync_mode: SyncMode }) => void }) {
  const [name, setName] = useState(""); const [roles, setRoles] = useState("");
  const submit = (event: FormEvent) => { event.preventDefault(); if (!name.trim()) return; onSubmit({ name: name.trim(), role_tags: roles.split(",").map((tag) => tag.trim()).filter(Boolean), default_sync_mode: "manual" }); setName(""); setRoles(""); };
  return <form className="compact-form" onSubmit={submit}><label>新资产<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：后端维护者" /></label><label>角色标签<input value={roles} onChange={(event) => setRoles(event.target.value)} placeholder="backend, maintainer" /></label><button type="submit">建立资产 <span>↗</span></button></form>;
}

function AssetLedger({ asset, projects, selectedProjectId, onSelectProject, onAct }: { asset: Asset; projects: Project[]; selectedProjectId: string | null; onSelectProject: (id: string | null) => void; onAct: (action: () => Promise<unknown>, success: string) => void }) {
  const [projectId, setProjectId] = useState("");
  const availableProjects = projects.filter((project) => !asset.projects.some((membership) => membership.project_id === project.id));
  return <><article className="asset-hero"><p className="eyebrow">{asset.status} / {syncLabel[asset.default_sync_mode]}</p><h3>{asset.name}</h3><p>{asset.description || "这是一个稳定的逻辑身份；工具安装和会话不会改变它。"}</p><div className="chip-row">{asset.role_tags.map((tag) => <span key={tag}>{tag}</span>)}</div></article>
    <section className="ledger-block"><h4>项目归属 <i>{asset.projects.length}</i></h4><div className="rows">{asset.projects.map((membership) => <button className={`row project-row ${selectedProjectId === membership.project_id ? "chosen" : ""}`} onClick={() => onSelectProject(selectedProjectId === membership.project_id ? null : membership.project_id)} key={membership.project_id}><b>{membership.project_id}</b><span>{membership.role || "成员"}</span><em>{syncLabel[membership.sync_mode]}</em></button>)}</div><div className="inline-form"><select value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">关联已有项目…</option>{availableProjects.map((project) => <option key={project.id} value={project.id}>{project.name} / {project.id}</option>)}</select><button disabled={!projectId} onClick={() => { onAct(() => api.addProject(asset.id, { project_id: projectId, sync_mode: "manual" }), "项目已关联"); setProjectId(""); }}>关联</button></div><ProjectForm onSubmit={(body) => onAct(async () => { const project = await api.createProject(body); await api.addProject(asset.id, { project_id: project.id, sync_mode: "manual" }); onSelectProject(project.id); }, "项目已创建并关联")} /></section>
    <section className="ledger-block"><h4>工具端点 <i>{asset.endpoints.length}</i></h4><div className="rows">{asset.endpoints.map((endpoint) => <EndpointCard key={endpoint.endpoint_id} endpoint={endpoint} assetId={asset.id} onAct={onAct} />)}</div>{asset.endpoints.length === 0 && <Empty text="尚未绑定 Cursor、Codex 或 Claude 端点。" />}<EndpointForm onSubmit={(body) => onAct(() => api.addEndpoint(asset.id, body), "端点已绑定到资产")} /><p className="hint">已绑定端点的检索会使用该资产的有效记忆集。</p></section>
  </>;
}

function EndpointCard({ endpoint, assetId, onAct }: { endpoint: Endpoint; assetId: string; onAct: (action: () => Promise<unknown>, success: string) => void }) {
  const [drawer, setDrawer] = useState<EndpointSetupResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [profile, setProfile] = useState<LaunchProfile>("installed");
  const [repositoryPath, setRepositoryPath] = useState("");
  const [dbPath, setDbPath] = useState("");

  const open = async () => {
    setError(null);
    try {
      const payload = await api.endpointSetup(assetId, endpoint.endpoint_id, {
        profile,
        repository_path: repositoryPath || undefined,
        db_path: dbPath || undefined,
      });
      setDrawer(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法生成配置");
    }
  };
  const close = () => { setDrawer(null); setError(null); };
  const copy = async () => {
    if (!drawer) return;
    await navigator.clipboard.writeText(JSON.stringify(drawer.config, null, 2));
    onAct(async () => Promise.resolve(), "配置已复制到剪贴板");
  };
  const download = () => {
    if (!drawer) return;
    const blob = new Blob([JSON.stringify(drawer.config, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `mcp-${endpoint.platform}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className={`row endpoint-row status-${endpoint.status}`}>
      <header>
        <b>{endpoint.platform}</b>
        <span>{endpoint.client_id}</span>
        <em className={`status-pill ${endpoint.status}`} title={statusHint[endpoint.status]}>{statusLabel[endpoint.status]}</em>
      </header>
      <dl className="endpoint-meta">
        <dt>最近调用</dt><dd>{endpoint.last_operation ?? "—"}</dd>
        <dt>最近时间</dt><dd>{endpoint.last_seen_at ? new Date(endpoint.last_seen_at).toLocaleString() : "—"}</dd>
        <dt>可见记忆</dt><dd>{endpoint.visible_memory_count}</dd>
        {endpoint.last_error_category && <><dt>错误类别</dt><dd>{endpoint.last_error_category}</dd></>}
      </dl>
      <p className="status-hint">{statusHint[endpoint.status]}</p>
      <div className="endpoint-actions">
        <select value={profile} onChange={(e) => setProfile(e.target.value as LaunchProfile)}>
          <option value="installed">已安装命令</option>
          <option value="repository">仓库内运行 (uv)</option>
        </select>
        {profile === "repository" && (
          <input
            value={repositoryPath}
            onChange={(e) => setRepositoryPath(e.target.value)}
            placeholder="仓库绝对路径"
          />
        )}
        <input
          value={dbPath}
          onChange={(e) => setDbPath(e.target.value)}
          placeholder="可选：MW_DB_PATH 绝对路径"
        />
        <button onClick={open}>生成配置</button>
      </div>
      {error && <p className="inline-error">{error}</p>}
      {drawer && (
        <div className="setup-drawer" role="dialog" aria-label="MCP setup">
          <header>
            <strong>{drawer.platform} 配置片段</strong>
            <button onClick={close} aria-label="关闭">×</button>
          </header>
          <pre className="setup-json">{JSON.stringify(drawer.config, null, 2)}</pre>
          <footer>
            <small>将片段粘贴到客户端配置文件前，请确认目标路径。本工具不会自动写入任何 IDE 配置。</small>
            <div>
              <button onClick={copy}>复制 JSON</button>
              <button onClick={download}>下载</button>
            </div>
          </footer>
        </div>
      )}
    </div>
  );
}

function ProjectForm({ onSubmit }: { onSubmit: (body: { id: string; name: string }) => void }) { const [name, setName] = useState(""); const [id, setId] = useState(""); return <form className="project-form" onSubmit={(event) => { event.preventDefault(); if (name && id) { onSubmit({ name, id }); setName(""); setId(""); } }}><input value={name} onChange={(event) => setName(event.target.value)} placeholder="新项目名称" /><input value={id} onChange={(event) => setId(event.target.value)} placeholder="project-id" /><button type="submit">新建并关联</button></form>; }

function EndpointForm({ onSubmit }: { onSubmit: (body: { client_id: string; platform: string; display_name?: string }) => void }) {
  const [clientId, setClientId] = useState(""); const [platform, setPlatform] = useState("codex");
  return <form className="endpoint-form" onSubmit={(event) => { event.preventDefault(); if (clientId) { onSubmit({ client_id: clientId, platform }); setClientId(""); } }}><select value={platform} onChange={(event) => setPlatform(event.target.value)}><option value="codex">Codex</option><option value="claude">Claude</option><option value="cursor">Cursor</option><option value="custom">Custom</option></select><input value={clientId} onChange={(event) => setClientId(event.target.value)} placeholder="client-id" /><button type="submit">绑定端点</button></form>;
}

function MemoryRouting({ asset, allMemories, selectedProjectId, onAct }: { asset: Asset; allMemories: Memory[]; selectedProjectId: string | null; onAct: (action: () => Promise<unknown>, success: string) => void }) {
  const [mode, setMode] = useState<SyncMode>("manual"); const visible = new Set(asset.memories.map((memory) => memory.id)); const directGrant = new Set(asset.grants.map((grant) => grant.memory_id));
  const displayedMemories = selectedProjectId ? allMemories.filter((memory) => memory.scope.project_id === selectedProjectId) : allMemories;
  const correct = (memory: Memory) => { const content = window.prompt("纠正记忆内容", memory.content); if (content !== null && content.trim()) onAct(() => api.correctMemory(memory, content.trim()), "已创建纠正后的新版本"); };
  return <><p className="routing-copy">{selectedProjectId ? `正在查看项目 ${selectedProjectId} 的 active 记忆。` : "显示该资产可路由的 active 规范记忆。"} “授予”只建立引用，不复制内容；“撤销”会停止显式同步。</p><div className="mode-toggle"><button className={mode === "manual" ? "on" : ""} onClick={() => setMode("manual")}>手动</button><button className={mode === "automatic" ? "on" : ""} onClick={() => setMode("automatic")}>自动</button></div><div className="memory-list">{displayedMemories.map((memory) => <article className={`memory-card ${visible.has(memory.id) ? "visible" : ""}`} key={memory.id}><header><span>{memory.kind}</span><time>{memory.scope.level}{memory.scope.project_id ? `:${memory.scope.project_id}` : ""}</time></header><p>{memory.content}</p><footer><small>{visible.has(memory.id) ? (directGrant.has(memory.id) ? "显式授权" : "由 scope 可见") : "未路由"}</small><span>{directGrant.has(memory.id) ? <button onClick={() => onAct(() => api.removeGrant(asset.id, memory.id), "已撤销显式授权")}>撤销</button> : !visible.has(memory.id) ? <button onClick={() => onAct(() => api.addGrant(asset.id, memory.id, mode), "记忆已授予该资产")}>授予</button> : null}<button className="text-button" onClick={() => correct(memory)}>纠正</button></span></footer></article>)}{displayedMemories.length === 0 && <Empty text="该视图中还没有 active 记忆。" />}</div></>;
}
function Empty({ text }: { text: string }) { return <p className="empty">{text}</p>; }
createRoot(document.getElementById("root")!).render(<App />);
