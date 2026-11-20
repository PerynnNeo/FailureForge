export type ScenarioResult = {
  candidate_id: string; title: string; hypothesis: string; family_key: string | null;
  assumptions: string[]; state: string; reason: string | null; reference_run_id: string | null;
  variant_run_id: string | null; suite_id: string | null; applied_change: string | null;
  measurement: { name: string; unit: string; value: number | null; reference_value: number | null; limit: number | null } | null;
};

export type BatchReport = {
  batch_id: string; target: number | null; generation_status: string; run_supported: boolean;
  execution_error: string | null; rows: ScenarioResult[];
  counts: { proposed: number; submitted: number; assessed: number; passed: number; failed: number;
    measurement_only: number; blocked: number; pending: number; inconclusive: number };
};

const verdicts: Record<string, string> = {
  passed: 'Passed', failed: 'Failed', measurement_only: 'Measurement only', inconclusive: 'Inconclusive',
  queued: 'Queued', running: 'Simulating', ready: 'Ready to test', needs_information: 'Needs information',
  needs_capability: 'Needs model support', invalid: 'Invalid setup', stale: 'Older revision', dismissed: 'Dismissed',
};
export const verdictLabel = (state: string) => verdicts[state] ?? state.replaceAll('_', ' ');

export function reportInProgress(report: BatchReport) {
  return ['queued', 'running'].includes(report.generation_status) || report.counts.pending > 0;
}

export function coverageText(report: BatchReport) {
  const { assessed, submitted } = report.counts;
  if (!report.target) return `${assessed} of ${submitted} submitted cases assessed`;
  return `${assessed} of ${report.counts.proposed} proposed cases assessed · Target ${report.target} cases`;
}
