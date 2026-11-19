import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import '@fontsource-variable/space-grotesk';
import './landing.css';

const ForgeScene = lazy(() => import('./ForgeScene'));
type Scenario = 'placement' | 'obstacles' | 'grip';
const concepts: { id: Scenario; label: string; question: string }[] = [
  { id: 'placement', label: 'Object placement', question: 'What if the target moves?' },
  { id: 'obstacles', label: 'Obstacles', question: 'What if the path is blocked?' },
  { id: 'grip', label: 'Grip & contact', question: 'What if the grasp changes?' },
];
const steps = [
  { name: 'Define the experiment', title: 'Give the robot a task.', text: 'Start with a supported robot and its controller. Set the task, the conditions to explore, and what counts as success.', detail: 'Robot · Controller · Task · Test bounds' },
  { name: 'Explore the conditions', title: 'Look beyond the ideal run.', text: 'Run controlled variations in simulation. Compare outcomes against reference conditions and find the attempts that deserve attention.', detail: 'Bounded search · Matched comparisons' },
  { name: 'Investigate the failure', title: 'Turn an outcome into evidence.', text: 'Inspect what happened, try a smaller change, and run the case again. Keep the full context, including reruns that disagree.', detail: 'Recordings · Traces · Reproduction bundle' },
];
const clamp = (value: number) => Math.max(0, Math.min(1, value));

function ForgeMark() {
  return <svg viewBox="0 0 38 38" fill="none" aria-hidden="true"><path d="M5 5h28v8H14v6h15v8H14v6H5V5Z" fill="currentColor"/><path d="M24 29h9v4h-9z" fill="#ff784b"/></svg>;
}
function Crosshair() {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M8 12h8m-4-4v8" stroke="currentColor" strokeWidth="1.5"/></svg>;
}
function Plus() { return <span className="ff-plus" aria-hidden="true">+</span>; }

function MiniWorld({ variant = 0, paths = false }: { variant?: number; paths?: boolean }) {
  const shifted = variant % 3;
  return <svg viewBox="0 0 300 210" aria-hidden="true">
    <path d="m24 146 116-67 137 77-115 66Z" fill="#262e2a" stroke="#4d5b51"/>
    <path d="m51 145 113 65m-85-82 113 65m-86-82 113 65M54 162l112-64m-84 81 112-65m-84 82 112-66" stroke="#3d4841"/>
    <ellipse cx="104" cy="147" rx="25" ry="14" fill="#111815"/>
    <path d="M84 145v-21h39v21q-19 12-39 0" fill="#758078"/>
    <path d="m104 123-17-49 43-37 43 24 8 36" fill="none" stroke="#bac2b9" strokeWidth="15" strokeLinejoin="round"/>
    <path d="m104 123-17-49 43-37 43 24 8 36" fill="none" stroke="#d7ddd2" strokeWidth="8" strokeLinejoin="round"/>
    <circle cx="87" cy="74" r="12" fill="#17221b" stroke="#8d9b8c" strokeWidth="4"/>
    <circle cx="130" cy="37" r="10" fill="#17221b" stroke="#8d9b8c" strokeWidth="3"/>
    <path d="m174 97 2 15m12-18 3 15" stroke="#b3bdb0" strokeWidth="5"/>
    <g transform={`translate(${shifted * 17} ${shifted * 4})`}><path d="m166 142 18-10 18 10-18 11Z" fill="#ff9a73"/><path d="m166 142 18 11v20l-18-11Z" fill="#e56841"/><path d="m184 153 18-11v20l-18 11Z" fill="#a7492d"/></g>
    {variant > 2 && <g><path d="m205 112 15-8 22 13-15 9Z" fill="#98a58f"/><path d="m205 112 22 14v31l-22-13Z" fill="#65725f"/><path d="m227 126 15-9v31l-15 9Z" fill="#45523e"/></g>}
    {paths && <path d={shifted ? 'M181 113 Q227 103 226 162' : 'M181 113 Q185 125 184 142'} fill="none" stroke="#ff845a" strokeWidth="2" strokeDasharray="4 5"/>}
  </svg>;
}

function ScenarioGraphic({ kind }: { kind: 'arrangement' | 'contact' | 'perception' }) {
  return <div className={`ff-family-art ff-family-${kind}`} aria-hidden="true"><svg viewBox="0 0 420 280" fill="none">
    <path d="m43 193 162-95 172 100-163 94Z" fill="#e0e4dc" stroke="#b6c0b1"/>
    <path d="m83 192 130 76m-90-99 130 76m-90-99 130 76M84 217l129-76m-89 99 129-76m-89 99 129-76" stroke="#c2cbbd"/>
    {kind === 'arrangement' ? <>
      <path d="m117 150 38-22 39 22-39 23Zm0 0v45l38 22v-44m39-23v45l-39 22" stroke="#8d9c86" strokeDasharray="5 5"/>
      <g className="ff-layout-cube"><path d="m222 161 38-22 39 22-39 23Z" fill="#ff996e" stroke="#d96e45"/><path d="m222 161 38 23v45l-38-23Z" fill="#ee8054"/><path d="m260 184 39-23v45l-39 23Z" fill="#c85b36"/></g>
      <path d="M155 125q38-44 104 9" stroke="#7b8c72" strokeDasharray="4 5"/><path d="m184 206 11-6 49 28-11 7Z" fill="#a4b096"/>
    </> : kind === 'contact' ? <>
      <path d="m150 66 16 54-9 40m106-94-16 54 9 40" stroke="#66765e" strokeWidth="19" strokeLinecap="square"/>
      <path d="m150 66 16 54-9 40m106-94-16 54 9 40" stroke="#bac4b0" strokeWidth="10"/>
      <g className="ff-contact-object"><ellipse cx="207" cy="145" rx="39" ry="22" fill="#ffa37b"/><path d="M168 145v47q39 37 78 0v-47q-39 33-78 0Z" fill="#e6794d"/><ellipse cx="207" cy="145" rx="39" ry="22" stroke="#c25937"/></g>
      <path d="M207 210v44m-8-10 8 10 8-10" stroke="#7f8f73" strokeDasharray="4 5"/><path d="M120 195q-19-32 0-57m173 57q19-32 0-57" stroke="#a2b093"/>
    </> : <>
      <path d="m189 157 31-18 32 18-32 19Z" fill="#88977e"/><path d="m189 157 31 19v36l-31-18Z" fill="#5d7152"/><path d="m220 176 32-19v36l-32 19Z" fill="#405438"/>
      <path d="M91 99 163 197 291 185Z" fill="#ed8755" fillOpacity=".12" stroke="#dd895b" strokeDasharray="5 5"/>
      <path d="M68 77h43v34H68Zm43 8 15-9v35l-15-8" fill="#627658" stroke="#3d5535"/>
      <circle cx="89" cy="94" r="8" fill="#cbd5c2"/>
      <circle cx="300" cy="72" r="19" stroke="#a0ac94"/><path d="M300 40V29m0 86v-11m32-32h11m-86 0h11m9-23-8-8m54 54 8 8m-8-54 8-8m-54 54-8 8" stroke="#a0ac94"/>
    </>}
  </svg></div>;
}

function WorkflowVisual({ step }: { step: number }) {
  return <div className={`ff-process-visual ff-process-state-${step}`}>
    <div className="ff-process-window"><span><ForgeMark/>EXPERIMENT WORKSPACE</span><span>CONCEPT WALKTHROUGH</span></div>
    {step === 0 ? <div className="ff-define-visual">
      <div className="ff-blueprint"><MiniWorld paths/><div className="ff-blueprint-target"><Crosshair/><span>Task + environment</span></div></div>
      <div className="ff-contract"><div><span>ROBOT</span><strong>Simulated embodiment</strong></div><div><span>CONTROLLER</span><strong>The behavior being tested</strong></div><div><span>EXPERIMENT</span><strong>Task, bounds & outcome rules</strong></div></div>
    </div> : step === 1 ? <div className="ff-trials-visual">
      <div className="ff-trial-heading"><span>One experiment. Controlled variations.</span><Crosshair/></div>
      <div className="ff-trial-grid">{Array.from({ length: 6 }, (_, i) => <div key={i} className={i === 4 ? 'ff-trial-selected' : ''}><MiniWorld variant={i} paths/>{i === 4 && <span>Inspect this case</span>}</div>)}</div>
      <div className="ff-trial-caption">Outcomes come from execution. Every attempt stays in the record.</div>
    </div> : <div className="ff-case-visual">
      <div className="ff-case-pair"><div><span>REFERENCE CONDITIONS</span><MiniWorld paths/></div><div><span>CHANGED CONDITIONS</span><MiniWorld variant={4} paths/></div></div>
      <div className="ff-trace-label"><span>ACTIONS + STATE</span><span>Compare the evidence</span></div>
      <svg className="ff-case-trace" viewBox="0 0 600 90" aria-hidden="true"><path d="M0 20H600M0 45H600M0 70H600" stroke="#344137"/><path d="m0 60 40-8 40 5 40-30 40 10 40-20 40 8 40-3 40 23 40-6 40 14 40-21 40 7 40-18 40 5 40-4" stroke="#b7c7aa" fill="none" strokeWidth="2"/><path d="m0 60 40-8 40 5 40-30 40 10 40-20 40 8 40 12 40-7 40 11 40-2 40 31 40-6 40 9 40-2 40 4" stroke="#fa8054" fill="none" strokeWidth="2"/></svg>
      <div className="ff-case-manifest"><span>Scene configuration</span><span>Recorded behavior</span><span>Rerun history</span></div>
    </div>}
    <div className="ff-process-caption"><span>Illustrative workflow · not experiment results</span><span>{steps[step].name}</span></div>
  </div>;
}

export default function LandingPage() {
  const [menu, setMenu] = useState(false);
  const [paused, setPaused] = useState(false);
  const [reduced, setReduced] = useState(false);
  const [scenario, setScenario] = useState<Scenario>('placement');
  const [step, setStep] = useState(0);
  const [progress, setProgress] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const process = useRef<HTMLElement>(null);
  const navToggle = useRef<HTMLButtonElement>(null);
  const activeConcept = concepts.find(item => item.id === scenario)!;

  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    const motion = () => { setReduced(media.matches); setPaused(media.matches); };
    motion(); media.addEventListener('change', motion);
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.add('ff-visible'); observer.unobserve(entry.target); }
    }), { threshold: .1 });
    root.current?.querySelectorAll('.ff-reveal').forEach(el => observer.observe(el));
    let frame = 0;
    const update = () => {
      frame = 0;
      setProgress(clamp(window.scrollY / Math.max(window.innerHeight, 1)));
      if (process.current && window.innerWidth > 1000 && window.innerHeight > 690) {
        const box = process.current.getBoundingClientRect();
        setStep(Math.min(2, Math.floor(clamp((80 - box.top) / Math.max(1, box.height - window.innerHeight)) * 3)));
      }
    };
    const scroll = () => { if (!frame) frame = requestAnimationFrame(update); };
    update(); window.addEventListener('scroll', scroll, { passive: true }); window.addEventListener('resize', scroll);
    return () => { media.removeEventListener('change', motion); observer.disconnect(); cancelAnimationFrame(frame); window.removeEventListener('scroll', scroll); window.removeEventListener('resize', scroll); };
  }, []);
  useEffect(() => {
    if (!menu) return;
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') { setMenu(false); navToggle.current?.focus(); } };
    window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close);
  }, [menu]);
  function goTo(id: string) { setMenu(false); document.getElementById(id)?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' }); }
  function chooseStep(index: number) {
    setStep(index);
    if (window.innerWidth > 1000 && window.innerHeight > 690 && process.current) {
      const top = window.scrollY + process.current.getBoundingClientRect().top;
      const distance = process.current.offsetHeight - window.innerHeight;
      window.scrollTo({ top: top - 80 + distance * (index === 0 ? .04 : index === 1 ? .49 : .91), behavior: reduced ? 'auto' : 'smooth' });
    }
  }

  return <div className="landing-page" ref={root}>
    <a className="ff-skip" href="#ff-main" onClick={e => { e.preventDefault(); document.getElementById('ff-main')?.focus(); }}>Skip to content</a>
    <header className="ff-nav">
      <a className="ff-brand" href="#/" aria-label="FailureForge home" onClick={e => { e.preventDefault(); window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' }); }}><ForgeMark/><span>FailureForge</span></a>
      <nav id="ff-navigation" className={menu ? 'ff-nav-links ff-menu-open' : 'ff-nav-links'} aria-label="Website navigation"><button onClick={() => goTo('ff-purpose')}>The idea</button><button onClick={() => goTo('ff-scenarios')}>The scenarios</button><button onClick={() => goTo('ff-process')}>How it works</button><a className="ff-mobile-workbench" href="#/projects">Open workbench</a></nav>
      <a className="ff-nav-cta" href="#/projects">Open workbench<Plus/></a>
      <button ref={navToggle} className="ff-menu-toggle" aria-controls="ff-navigation" aria-expanded={menu} aria-label={menu ? 'Close navigation' : 'Open navigation'} onClick={() => setMenu(v => !v)}>{menu ? 'Close' : 'Menu'}<span aria-hidden="true">{menu ? '−' : '+'}</span></button>
    </header>
    <main id="ff-main" tabIndex={-1}>
      <section className="ff-hero" aria-labelledby="ff-hero-title">
        <div className="ff-hero-grid" aria-hidden="true"/>
        <div className="ff-hero-copy"><div className="ff-eyebrow"><i/>ROBOT FAILURE DISCOVERY / IN SIMULATION</div><h1 id="ff-hero-title">Find where<br/>robots <em>fail.</em></h1><p>Explore the situations that challenge a robot. Find failing cases, inspect what happened, and test whether the failure repeats.</p><div className="ff-hero-actions"><a className="ff-button ff-button-orange" href="#/projects/new">Start a project<Plus/></a><button className="ff-text-button" onClick={() => goTo('ff-purpose')}>Explore the idea<span className="ff-small-square"/></button></div></div>
        <div className="ff-hero-art"><div className="ff-scene" role="img" aria-label={`Concept illustration of a robot in a simulated workcell. ${activeConcept.question} This is artwork, not a recorded robot experiment.`}><Suspense fallback={<div className="ff-scene-loading"><ForgeMark/><span>ASSEMBLING THE WORKCELL</span></div>}><ForgeScene scenario={scenario} progress={progress} paused={paused}/></Suspense></div><div className="ff-workcell-label"><Crosshair/><span>VIRTUAL TEST ENVIRONMENT</span></div><div className="ff-world-question" aria-live="polite"><span>THE QUESTION</span><p>{activeConcept.question}</p></div></div>
        <div className="ff-hero-bottom"><div className="ff-concept-controls"><span>EXPLORE THE CONCEPT</span><div className="ff-scenario-buttons" role="group" aria-label="Illustrative scenarios, planned capabilities">{concepts.map(item => <button key={item.id} aria-pressed={scenario === item.id} onClick={() => setScenario(item.id)}>{item.label}</button>)}{!reduced && <button className="ff-motion-button" onClick={() => setPaused(v => !v)} aria-label={paused ? 'Play illustration motion' : 'Pause illustration motion'}><span aria-hidden="true">{paused ? '▷' : 'Ⅱ'}</span></button>}</div><p>Concept illustration · Scenario capabilities shown are planned.</p></div><button className="ff-scroll-cue" onClick={() => goTo('ff-purpose')}><span>SCROLL TO EXPLORE</span><i/></button></div>
      </section>

      <section id="ff-purpose" className="ff-purpose ff-section">
        <div className="ff-section-label ff-reveal"><span>THE IDEA</span><Crosshair/></div>
        <div className="ff-purpose-body ff-reveal"><h2>A successful demo<br/>is a <em>starting point.</em></h2><div className="ff-purpose-columns"><p className="ff-large-copy">What happens when the world changes?</p><p>FailureForge is a workbench for investigating robot behavior in simulation. Put an existing controller through a task, explore controlled changes, and keep the evidence behind the outcome.</p></div></div>
        <div className="ff-purpose-equation ff-reveal"><div><span>THE SYSTEM</span><strong>Robot + controller</strong></div><Plus/><div><span>THE CHALLENGE</span><strong>A task. A changing world.</strong></div><Plus/><div><span>THE FINDING</span><strong>A case you can investigate.</strong></div></div>
      </section>

      <section className="ff-scenarios ff-section" id="ff-scenarios">
        <div className="ff-scenarios-heading ff-reveal"><div className="ff-section-label"><span>THE SCENARIOS</span><Crosshair/></div><h2>Change the situation.<br/><em>Ask a harder question.</em></h2><p>The ambition is broader scenario testing. Each family asks a different question about the robot’s behavior.</p></div>
        <div className="ff-scenario-families">
          <article className="ff-family ff-reveal"><div className="ff-family-top"><span>ARRANGEMENT</span><span className="ff-tag">Planned</span></div><ScenarioGraphic kind="arrangement"/><h3>Can it still reach<br/>what matters?</h3><p>Move the object. Add clutter. Constrain the approach. Explore how the layout changes the task.</p><div className="ff-family-foot">Object positions · Obstacles · Clutter</div></article>
          <article className="ff-family ff-reveal"><div className="ff-family-top"><span>INTERACTION</span><span className="ff-tag">Planned</span></div><ScenarioGraphic kind="contact"/><h3>Will the grasp<br/>still hold?</h3><p>Change the object and its physical properties. Investigate the effects of contact, weight, and friction.</p><div className="ff-family-foot">Object properties · Grip · Contact</div></article>
          <article className="ff-family ff-reveal"><div className="ff-family-top"><span>PERCEPTION</span><span className="ff-tag ff-tag-current">First integration</span></div><ScenarioGraphic kind="perception"/><h3>What if the robot<br/>sees it differently?</h3><p>Change the robot’s camera view and the lighting. Test how altered observations affect its actions.</p><div className="ff-family-foot">Camera position · Lighting</div></article>
        </div>
        <p className="ff-scenario-note">Arrangement and interaction are product directions. The current robot integration explores perception changes in one supported task.</p>
      </section>

      <section id="ff-process" className="ff-process" ref={process} aria-labelledby="ff-process-title">
        <div className="ff-process-sticky">
          <div className="ff-process-heading"><div className="ff-section-label"><span>HOW IT WORKS</span><Crosshair/></div><h2 id="ff-process-title">Simulate.<br/>Investigate.<br/><em>Understand.</em></h2></div>
          <div className="ff-process-art"><WorkflowVisual step={step}/><div className="ff-process-progress" aria-hidden="true" style={{ '--ff-progress': `${(step + 1) / 3 * 100}%` } as CSSProperties}/></div>
          <div className="ff-process-steps" role="group" aria-label="Investigation workflow">{steps.map((item, index) => <button className={step === index ? 'ff-process-step ff-active' : 'ff-process-step'} key={item.name} aria-pressed={step === index} onClick={() => chooseStep(index)}><span className="ff-step-name">{item.name}<span aria-hidden="true">{step === index ? '−' : '+'}</span></span><strong>{item.title}</strong><span className="ff-step-text">{item.text}</span><small>{item.detail}</small></button>)}</div>
        </div>
      </section>

      <section className="ff-evidence ff-section" id="ff-evidence">
        <div className="ff-evidence-title ff-reveal"><div className="ff-section-label"><span>THE OUTPUT</span><Crosshair/></div><h2>A failure is useful<br/>when you can<br/><em>look closer.</em></h2><p>Keep the experiment with the result. Follow a case from its conditions to its outcome, then return to it with a better question.</p></div>
        <div className="ff-evidence-list ff-reveal"><article><span className="ff-evidence-icon"><Crosshair/></span><div><h3>See what happened.</h3><p>Inspect paired recordings from reference and changed conditions, together with the robot’s actions and state.</p></div></article><article><span className="ff-evidence-icon"><span aria-hidden="true">±</span></span><div><h3>Isolate what changed.</h3><p>Attempt a smaller variation that still exposes the failure. Preserve the original case and the search history.</p></div></article><article><span className="ff-evidence-icon"><span aria-hidden="true">↻</span></span><div><h3>Return to the same question.</h3><p>Request fresh execution and export the configuration, provenance, traces, and outcomes in one portable bundle.</p></div></article><a href="#/workspace" className="ff-text-link">Explore the investigation workspace<Plus/></a></div>
      </section>

      <section className="ff-release ff-section" id="ff-release">
        <div className="ff-release-heading ff-reveal"><div className="ff-section-label"><span>WHERE WE ARE TODAY</span><Crosshair/></div><h2>One controlled benchmark.<br/><em>A foundation to build on.</em></h2><p>The first integration uses a simulated Panda arm, a pretrained SmolVLA controller, and a LIBERO task: move a black bowl onto a plate. Camera position and lighting are the first conditions it explores.</p></div>
        <div className="ff-release-details ff-reveal"><div className="ff-release-status"><span>AVAILABLE NOW</span><h3>The diagnostic workbench.</h3><p>Prepare projects with assets, parameter provenance, and test plans. Explore the existing benchmark using explicitly labeled synthetic test data.</p><a href="#/workspace">Open workbench<Plus/></a></div><div className="ff-release-status"><span>AWAITING VALIDATION</span><h3>Robot-policy execution.</h3><p>The real simulator integration awaits qualification on the RTX 5090 execution host.</p><a href="#/runtime">View runtime setup<Plus/></a></div></div>
      </section>

      <section className="ff-faq ff-section"><div className="ff-section-label ff-reveal"><span>A FEW GOOD QUESTIONS</span><Crosshair/></div><div className="ff-faq-list ff-reveal">
        <details><summary>Do I need a physical robot?<Plus/></summary><p>No. The workflow runs a robot and its controller in a physics simulator. The initial integration supplies a supported robot, task, and pretrained controller. A physical robot is not required to run those simulated experiments.</p></details>
        <details><summary>Can I test my own robot or task?<Plus/></summary><p>You can create a project for a concept, CAD design, robot model, existing simulation, or physical prototype. Attach supporting files, record physical properties, and plan tests. Custom robot execution and structural or thermal solvers are planned; the executable benchmark remains one supported robot, task, and controller.</p></details>
        <details><summary>Is FailureForge training the robot?<Plus/></summary><p>FailureForge evaluates an existing controller—the software that decides how the robot acts. It searches for failures and packages evidence for investigation. It does not currently train or repair the controller.</p></details>
        <details><summary>Are the animations actual test results?<Plus/></summary><p>The illustrations explain the product’s purpose and direction. They are not recorded rollouts. The laptop workbench currently uses labeled synthetic diagnostics; robot experiment recordings require the qualified simulation runtime.</p></details>
        <details><summary>Does a simulation prove a robot is safe?<Plus/></summary><p>Simulation helps discover and investigate failures inside a defined test domain. Its results depend on the model, controller, environment, and conditions tested. They do not certify real-world robot safety.</p></details>
      </div></section>

      <section className="ff-final"><div className="ff-final-grid" aria-hidden="true"/><div className="ff-section-label"><span>BUILT FOR THE NEXT QUESTION</span><Crosshair/></div><h2 className="ff-reveal">Find the failure.<br/><em>Keep the insight.</em></h2><div className="ff-final-bottom"><p>Start with an experiment.<br/>Leave with a case you can investigate.</p><a className="ff-button ff-button-dark" href="#/projects">Open FailureForge<Plus/></a></div></section>
    </main>
    <footer className="ff-footer"><a className="ff-brand" href="#/" aria-label="FailureForge home" onClick={e => { e.preventDefault(); window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' }); }}><ForgeMark/><span>FailureForge</span></a><p>Robot behavior. Under investigation.</p><div><a href="#/runtime">Runtime & setup</a><button onClick={() => window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' })}>Back to top</button></div><span className="ff-footer-bottom">SIMULATED WORLDS. BETTER QUESTIONS.</span></footer>
  </div>;
}
