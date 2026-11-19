import type { components } from './generated-api';

export type CampaignSpec = Required<Omit<components['schemas']['CampaignSpec'], 'schema_version'>>;
export type Backend = CampaignSpec['backend'];
export type Method = CampaignSpec['method'];
export type Scene = { main_camera_dx_m: number; light_scale: number };
export type Domain = components['schemas']['Domain'];
export type Health = {
  status: string;
  runtime_mode: 'offline' | Backend;
  worker: { online: boolean; backend: string | null; last_seen: string | number | null };
  readiness: { qualified: boolean; reason: string };
};
export type Catalog = {
  task: { name: string; suite: string; id: number | string };
  policy: { repo_id: string; revision: string };
  domain: Domain;
  methods: Method[];
  qualification?: Record<string, unknown>;
};
export type Budget = {
  attempted: number; completed: number; reserved: number; retries: number;
  limits: { baseline?: number; search: number; reduction: number; confirmation: number; rerun?: number; max_attempts: number };
};
export type Job = { id: string; status: string; kind?: string; phase?: string; error?: string | null; progress?: Record<string, unknown> };
export type Candidate = {
  id: string; index?: number; proposal_index?: number; scene_change: Scene;
  status: string; score?: number | null; failure_count?: number | null;
  failure_state_ids?: number[]; completed_states?: number; source?: string; reason?: string;
};
export type Episode = {
  id: string; state_id: number; condition: 'reference' | 'changed'; phase: string;
  outcome: string; steps: number; elapsed_seconds: number; scene_change: Scene;
  artifact_id?: string; artifacts?: { main_video?: string; wrist_video?: string; trace?: string };
  backend: Backend; seed?: number; policy_seed?: number;
};
export type CasePair = { state_id: number; reference?: string | Episode; changed?: string | Episode; reference_episode_id?: string; changed_episode_id?: string; phase?: string };
export type FailureCase = {
  id: string; campaign_id: string; backend: Backend; status: string; scene_change: Scene;
  original_scene_change?: Scene; failure_state_ids: number[]; episodes: Episode[];
  pairs?: CasePair[]; reduction_history?: Array<Record<string, unknown>>;
  search_pairs?: CasePair[]; reduction_initial_pairs?: CasePair[]; reduction_final_pairs?: CasePair[];
  confirmation_pairs?: CasePair[]; jobs?: Job[];
  confirmation_summary?: Record<string, unknown>; created_at?: string;
  reruns?: Array<{ job_id: string; pairs: CasePair[]; reproduced: boolean }>;
  [key: string]: unknown;
};
export type Campaign = {
  id: string; name: string; status: string; backend: Backend; spec: CampaignSpec;
  created_at: string; updated_at: string; budget: Budget; candidates?: Candidate[];
  episodes?: Episode[]; cases?: Array<FailureCase | { id: string; status?: string }>;
  jobs?: Job[];
};
