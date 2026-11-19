import type { RunDetail } from './analysisInputs';
import type { Condition } from './campaignCompare';
import { verdict } from './campaignVerdict';
import { comparisonMeasurements } from './comparisonMeasurements';
import { measuredNumber } from './recordedFields';

export function RunResult({ run, detail }: { run: Condition; detail: RunDetail | null }) {
  const record = detail?.id === run.id ? detail : null;
  const error = run.error || record?.assessment_error;
  const outcome = error ? 'Inconclusive' : verdict(run);
  const { measurements, outcomes } = record ? comparisonMeasurements(record) : { measurements: [], outcomes: [] };
  const hasLimit = measurements.some(row => row.maximum !== undefined);
  return <div className="compare-run-result">
    <h5>{run.label}</h5>
    <p className="compare-verdict">Verdict · <strong className={outcome === 'Passed' ? 'text-green' : outcome === 'Failed' ? 'text-red' : undefined}>{outcome}</strong></p>
    {error && <p className="small muted">{error}</p>}
    {measurements.length > 0 && <div className="analysis-table-scroll"><table className="data-table">
      <thead><tr><th>Measurement</th><th>Recorded value</th>{hasLimit && <th>Acceptance limit</th>}</tr></thead>
      <tbody>{measurements.map(row => <tr key={row.name}>
        <th scope="row">{row.name}</th><td>{measuredNumber(row.value)} {row.unit}</td>
        {hasLimit && <td>{row.maximum === undefined ? '—' : <>≤ {measuredNumber(row.maximum)} {row.unit}</>}
          {row.passed !== undefined && <small>{row.passed ? 'Passed' : 'Failed'}</small>}</td>}
      </tr>)}</tbody>
    </table></div>}
    {outcomes.length > 0 && <ul className="matrix-checks">{outcomes.map(check => <li key={check.name}>{check.name}
      <strong className={'matrix-tag ' + (check.passed ? 'passed' : 'failed')}>{check.passed ? 'Passed' : 'Failed'}</strong>
    </li>)}</ul>}
    {record && !measurements.length && !outcomes.length && <p className="small muted">No measurements recorded.</p>}
    {record && measurements.length > 0 && !hasLimit && outcome === 'Measurement only' &&
      <p className="small muted">No acceptance limit was recorded.</p>}
  </div>;
}
