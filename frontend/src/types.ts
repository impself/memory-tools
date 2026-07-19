export type SyncMode = "manual" | "automatic";
export type Platform = "codex" | "claude" | "cursor" | "custom";
export type EndpointStatus = "never_seen" | "active" | "stale";
export type LaunchProfile = "installed" | "repository";

export interface Memory { id: string; content: string; kind: string; state: string; source_id: string; supersedes_id: string | null; updated_at: string; scope: { level: string; project_id?: string | null; workspace_id?: string | null; agent_id?: string | null; session_id?: string | null }; }
export interface Endpoint {
  endpoint_id: string;
  asset_id: string;
  client_id: string;
  platform: Platform;
  status: EndpointStatus;
  last_seen_at: string | null;
  last_operation: string | null;
  last_error_category: string | null;
  visible_memory_count: number;
}
export interface Membership { asset_id: string; project_id: string; role: string | null; sync_mode: SyncMode; }
export interface Grant { id: string; memory_id: string; asset_id: string; sync_mode: SyncMode; }
export interface Asset { id: string; name: string; description: string | null; role_tags: string[]; default_sync_mode: SyncMode; status: string; endpoints: Endpoint[]; projects: Membership[]; grants: Grant[]; memories: Memory[]; memory_count: number; }
export interface Project { id: string; name: string; workspace_id: string | null; description: string | null; }

export interface EndpointSetupRequest {
  profile: LaunchProfile;
  repository_path?: string;
  db_path?: string;
}

export interface EndpointSetupResponse {
  endpoint_id: string;
  client_id: string;
  platform: Platform;
  profile: LaunchProfile;
  config: { mcpServers: Record<string, unknown> };
}
