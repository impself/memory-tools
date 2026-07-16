import type { Asset, Grant, Membership, Memory, Project, SyncMode } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...init?.headers }, ...init });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) { const detail = typeof body === "object" && body !== null && "detail" in body ? String(body.detail) : response.statusText; throw new Error(detail); }
  return body as T;
}
export const api = {
  assets: () => request<Asset[]>("/api/assets"), asset: (id: string) => request<Asset>(`/api/assets/${id}`), projects: () => request<Project[]>("/api/projects"), memories: () => request<Memory[]>("/api/memories?state=active&limit=200"),
  projectMemories: (id: string) => request<Memory[]>(`/api/projects/${id}/memories`),
  createAsset: (body: { name: string; description?: string; role_tags: string[]; default_sync_mode: SyncMode }) => request<Asset>("/api/assets", { method: "POST", body: JSON.stringify(body) }),
  createProject: (body: { id: string; name: string; description?: string }) => request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  addProject: (assetId: string, body: { project_id: string; role?: string; sync_mode: SyncMode }) => request<Membership>(`/api/assets/${assetId}/projects`, { method: "POST", body: JSON.stringify(body) }),
  addEndpoint: (assetId: string, body: { client_id: string; platform: string; display_name?: string }) => request(`/api/assets/${assetId}/endpoints`, { method: "POST", body: JSON.stringify(body) }),
  addGrant: (assetId: string, memoryId: string, syncMode: SyncMode) => request<Grant>(`/api/assets/${assetId}/grants`, { method: "POST", body: JSON.stringify({ memory_id: memoryId, sync_mode: syncMode }) }),
  removeGrant: (assetId: string, memoryId: string) => request(`/api/assets/${assetId}/grants/${memoryId}`, { method: "DELETE" }),
  correctMemory: (memory: Memory, content: string) => request<Memory>(`/api/memories/${memory.id}/correct`, { method: "POST", body: JSON.stringify({ content, client_id: "web-ui", scope: memory.scope }) }),
};
