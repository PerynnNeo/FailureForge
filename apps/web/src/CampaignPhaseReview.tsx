import { conditionStatusLabels } from './projectTypes';
import type { TaskPhase } from './projectTypes';

export type PhaseReview = {
  current_revision: number; current_phases: TaskPhase[];
  campaign_revision: number; campaign_phases: TaskPhase[] | null;
  submitted_condition: { phase_id: string; condition_id: string } | null;
};

function PhaseAnswers({ phases, submitted }: {
  phases: TaskPhase[]; submitted?: PhaseReview['submitted_condition'];
}) {
  if (!phases.length) return <p>No task phases were saved on this revision.</p>;
  return <div className="campaign-phase-list">{phases.map(phase =>
    <section key={phase.id}>
      <h5>{phase.name}</h5>
      {phase.question && <p>{phase.question}</p>}
      {phase.question && phase.conditions.length > 0 &&
        phase.conditions.every(condition => condition.question && condition.question.trim() !== phase.question.trim()) &&
        <p><em>Awaiting an answer to the current question.</em></p>}
      {phase.conditions.length ? <ul>{phase.conditions.map(condition =>
        <li key={condition.id}>
          <strong>{condition.subject || condition.answer}</strong> <span className="phase-answer-status">{conditionStatusLabels[condition.status]}</span>
          <p>{condition.reason}</p>
          {condition.next_step && <p><b>Next step</b> {condition.next_step}</p>}
          {condition.test && <p><b>Test control</b> <code>{condition.test.field}</code> · {condition.test.adapter.replaceAll('_', ' ')}</p>}
          {submitted?.phase_id === phase.id && submitted.condition_id === condition.id &&
            <p>This campaign was submitted for this condition.</p>}
          {(condition.subject && condition.subject !== condition.answer || condition.question && condition.question !== phase.question) &&
            <details><summary>Recorded answer</summary>
              {condition.question && <p>{condition.question}</p>}
              <p>{condition.answer}</p>
            </details>}
        </li>)}</ul> : <p><em>Awaiting a first answer.</em></p>}
    </section>
  )}</div>;
}

export function CampaignPhaseReview({ review, projectId }: { review: PhaseReview; projectId: string }) {
  const { current_phases: phases, current_revision: current, campaign_revision: original } = review;
  const conditions = phases.flatMap(phase => phase.conditions);
  const modeled = conditions.filter(condition => condition.status === 'modeled').length;
  return <section className="campaign-phase-review" aria-label="Task phase review">
    <h4>Task phase review</h4>
    <p>Current project revision {current} · Campaign revision {original}. Grid coverage counts the operating levels in this campaign.</p>
    {conditions.length > 0 && <p><strong>{modeled} of {conditions.length} recorded conditions have a solver test configured.</strong></p>}
    <PhaseAnswers phases={phases} submitted={current === original ? review.submitted_condition : null}/>
    <a className="text-link" href={'#/projects/' + encodeURIComponent(projectId) + '?tab=phases'}>Review task phases in project</a>
    {current !== original && <details>
      <summary>Phase review at campaign revision {original}</summary>
      {review.campaign_phases === null ? <p>This campaign revision has no recorded phase review.</p> :
        <PhaseAnswers phases={review.campaign_phases} submitted={review.submitted_condition}/>}
    </details>}
  </section>;
}
