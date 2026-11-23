export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(`/api${path}`, {
      ...options,
      signal: controller.signal,
      headers: { ...(options?.body ? { 'Content-Type': 'application/json' } : {}), ...options?.headers },
    });
    if (!response.ok) {
      const error = await response.json().catch(() => null);
      const detail = error?.detail;
      const message = typeof detail === 'string' ? detail : Array.isArray(detail)
        ? detail.map((item: { msg?: string; loc?: string[] }) => `${item.loc?.join('.') ?? 'Request'}: ${item.msg}`).join('; ')
        : error?.message || `Request failed (${response.status}).`;
      throw new ApiError(message, response.status);
    }
    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new Error('The API is unreachable. Start the local service and try again.');
  } finally { window.clearTimeout(timeout); }
}

export function post<T>(path: string, body: unknown = {}, key?: string): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body), headers: key ? { 'Idempotency-Key': key } : {} });
}

export function artifactUrl(value?: string): string | undefined {
  if (!value) return undefined;
  if (value.startsWith('/api/artifacts/')) return value;
  if (value.startsWith('/artifacts/')) return `/api${value}`;
  if (/^[a-zA-Z0-9_-]+$/.test(value)) return `/api/artifacts/${encodeURIComponent(value)}`;
  return undefined;
}

export { formatWorkspaceTime as formatTime } from './workspacePreferences.ts';
export const label = (value?: string) => (value ?? 'unknown').replaceAll('_', ' ');
export const shortId = (value: string) => value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
export const methodName = (value?: string) => ({ random: 'Uniform random', sobol: 'Sobol', sobol_local_mix: 'Sobol + local search' })[value ?? ''] ?? label(value);
