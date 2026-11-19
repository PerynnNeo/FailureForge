import { useState } from 'react';
import { artifactUrl, label, shortId } from './api';
import { Status } from './components';
import type { Campaign } from './types';

export default function CampaignEvidence({ campaign }: { campaign: Campaign }) {
  const [selectedId, setSelectedId] = useState('');
  const episodes = campaign.episodes ?? [];
  const episode = episodes.find(item => item.id === selectedId) ?? episodes[0];
  const candidateNumbers = new Map(campaign.candidates?.map((candidate, index) =>
    [candidate.id, (candidate.proposal_index ?? candidate.index ?? index) + 1] as const));
  const trace = artifactUrl(episode?.artifacts?.trace);
  const cameras = [
    { name: 'Main camera', url: artifactUrl(episode?.artifacts?.main_video) },
    { name: 'Wrist camera', url: artifactUrl(episode?.artifacts?.wrist_video) },
  ];

  return <section className="card episode-evidence">
    <div className="card-heading">
      <h3>Episode evidence</h3>
      {episode && <select aria-label="Recorded episode" value={episode.id} onChange={event => setSelectedId(event.target.value)}>
        {episodes.map((item, index) => {
          const number = item.candidate_id ? candidateNumbers.get(item.candidate_id) : undefined;
          const stage = number === undefined ? label(item.phase) : `Candidate ${number}`;
          return <option key={item.id} value={item.id}>
            {index + 1}. {stage} · state {item.state_id} · {label(item.outcome ?? item.status)}
          </option>;
        })}
      </select>}
    </div>
    {episode ? <>
      <div className="card-pad episode-summary">
        <Status value={episode.outcome ?? episode.status}/>
        <span>{label(episode.condition)} · {shortId(episode.id)}</span>
        {trace && <><span>{episode.steps} control steps</span>
          <a className="text-link" href={trace} download={`${episode.id}-traces.npz`}>Download trace (.npz)</a></>}
      </div>
      {campaign.backend === 'libero' && cameras.some(camera => camera.url) &&
        <div className="video-pair">
          {cameras.map(camera => camera.url && <div key={camera.name}>
            <div className="video-label">{camera.name}</div>
            <div className="video-surface">
              <video key={camera.url} src={camera.url} controls playsInline preload="metadata" aria-label={camera.name}/>
            </div>
          </div>)}
        </div>}
      {!trace && !cameras.some(camera => camera.url) &&
        <p className="card-pad small muted">This attempt has no published recording or trace.</p>}
    </> : <p className="card-pad small muted">Episodes will appear as the worker starts its reference checks.</p>}
  </section>;
}
