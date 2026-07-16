export type SyncMode = "manual" | "automatic";
export type Platform = "codex" | "claude" | "cursor" | "custom";
export interface Memory { id: string; content: string; kind: string; state: string; source_id: string; supersedes_id: string | null; updated_at: string; scope: { level: string; project_id?: string | null; workspace_id?: string | null }; }
export interface Endpoint { id: string; client_id: string; platform: Platform; display_name: string | null; }
export interface Membership { asset_id: string; project_id: string; role: string | null; sync_mode: SyncMode; }
export interface Grant { id: string; memory_id: string; asset_id: string; sync_mode: SyncMode; }
export interface Asset { id: string; name: string; description: string | null; role_tags: string[]; default_sync_mode: SyncMode; status: string; endpoints: Endpoint[]; projects: Membership[]; grants: Grant[]; memories: Memory[]; memory_count: number; }
export interface Project { id: string; name: string; workspace_id: string | null; description: string | null; }
