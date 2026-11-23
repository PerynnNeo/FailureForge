import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import '@fontsource-variable/space-grotesk';
import './landing.css';

const ForgeScene = lazy(() => import('./ForgeScene'));
const shelfExampleHref = '#/projects/new?example=shelf';
type Scenario = 'placement' | 'obstacles' | 'grip';
const concepts: { id: Scenario; label: string; question: string }[] = [
  { id: 'placement', label: 'Object placement', question: 'What if the target moves?' },
  { id: 'obstacles', label: 'Obstacles', question: 'What if the path is blocked?' },
  { id: 'grip', label: 'Grip & contact', question: 'What if the grasp changes?' },
];
const steps = [
  { name: 'Choose a reference', title: 'Describe normal operation.', text: 'Decide what the prototype should do and what you will measure. For the shelf example, the starting condition is a load spread along the shelf.', detail: 'Model inputs · Starting load · Bending limit' },
  { name: 'Run a comparison', title: 'Change one condition.', text: 'Move the same load to the free edge of the shelf. Run both conditions with the same material and dimensions so you can isolate the effect of load position.', detail: 'Reference condition · Changed condition' },
  { name: 'Read the result', title: 'Did it stay within the limit?', text: 'Compare the measured bend in each run with the allowed bend. Use the result to decide which condition to check on a physical prototype.', detail: 'Measurement · Limit · Verdict' },
];
const clamp = (value: number) => Math.max(0, Math.min(1, value));

function ForgeMark() {
  return <svg viewBox="0 0 38 38" fill="none" aria-hidden="true"><path d="M5 5h28v8H14v6h15v8H14v6H5V5Z" fill="currentColor"/><path d="M24 29h9v4h-9z" fill="#ff784b"/></svg>;
}
function Crosshair() {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M8 12h8m-4-4v8" stroke="currentColor" strokeWidth="1.5"/></svg>;
}
function Plus() { return <span className="ff-plus" aria-hidden="true">+</span>; }

function ShelfDiagram({ edge, measure }: { edge: boolean; measure: boolean }) {
  const arrows = edge ? [395] : [104, 162, 220, 278, 336, 394];
  return <svg className="ff-shelf-diagram" viewBox="0 0 460 205" aria-hidden="true">
    <g stroke="#4e6153" strokeWidth="1">
      {[65, 102, 139, 176].map(y => <path key={y} d={`M25 ${y}H435`}/>)}
    </g>
    <g fill="none" stroke="#ed956f" strokeWidth="3">
      {arrows.map(x => <path key={x} d={`M${x} 34v38m-5-6 5 6 5-6`}/>)}
    </g>
    <path d="M64 97H398" stroke="#b7c6af" strokeWidth="2" strokeDasharray="5 6"/>
    <path d={measure ? 'M64 97q202 0 334 42' : 'M64 97H398'} fill="none" stroke="#d5dfce" strokeWidth="9"/>
    <path d="M61 77v86m-9-73 9-9m-9 26 9-9m-9 26 9-9m-9 26 9-9m-9 26 9-9" fill="none" stroke="#9cab94" strokeWidth="3"/>
    {measure && <path d="M408 98h10m-5 0v40m-5 0h10" fill="none" stroke="#ed956f" strokeWidth="2"/>}
    <text x="43" y="188">FIXED END</text><text x="407" y="188" textAnchor="end">FREE EDGE</text>
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
  const captions = [
    'In the reference run, the load is spread along the shelf.',
    'In the comparison run, the same load rests at the free edge.',
    'Read the maximum bend for each run and compare it with the design limit.',
  ];
  return <figure className="ff-process-visual ff-shelf-visual">
    <div className="ff-process-window"><span><ForgeMark/>SHELF EXAMPLE</span><span>SETUP DIAGRAM</span></div>
    <ShelfDiagram edge={step > 0} measure={step === 2}/>
    <figcaption>{captions[step]}</figcaption>
    <a className="ff-text-link" href={shelfExampleHref}>Try the shelf example<Plus/></a>
  </figure>;
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
      <nav id="ff-navigation" className={menu ? 'ff-nav-links ff-menu-open' : 'ff-nav-links'} aria-label="Website navigation"><button onClick={() => goTo('ff-process')}>How it works</button><button onClick={() => goTo('ff-scenarios')}>Robot scenarios</button><a className="ff-mobile-workbench" href="#/projects">My projects</a></nav>
      <a className="ff-nav-cta" href="#/projects">My projects<Plus/></a>
      <button ref={navToggle} className="ff-menu-toggle" aria-controls="ff-navigation" aria-expanded={menu} aria-label={menu ? 'Close navigation' : 'Open navigation'} onClick={() => setMenu(v => !v)}>{menu ? 'Close' : 'Menu'}<span aria-hidden="true">{menu ? '−' : '+'}</span></button>
    </header>
    <main id="ff-main" tabIndex={-1}>
      <section className="ff-hero" aria-labelledby="ff-hero-title">
        <div className="ff-hero-grid" aria-hidden="true"/>
        <div className="ff-hero-copy">
          <div className="ff-eyebrow"><i/>PROTOTYPE TESTING / IN SIMULATION</div>
          <h1 id="ff-hero-title">What would<br/>make it <em>fail?</em></h1>
          <p>Start with a shelf. See how far it bends when the same load moves to its edge. The model, material and bending limit are already supplied.</p>
          <div className="ff-hero-actions">
            <a className="ff-button ff-button-orange" href={shelfExampleHref}>Try the shelf example<Plus/></a>
            <a className="ff-text-button" href="#/projects/new">Start my own project<span className="ff-small-square"/></a>
          </div>
        </div>
        <div className="ff-hero-art"><div className="ff-scene" role="img" aria-label={`Illustrated robot workcell. ${activeConcept.question}`}><Suspense fallback={<div className="ff-scene-loading"><ForgeMark/><span>ASSEMBLING THE WORKCELL</span></div>}><ForgeScene scenario={scenario} progress={progress} paused={paused}/></Suspense></div><div className="ff-workcell-label"><Crosshair/><span>ROBOT WORKCELL ILLUSTRATION</span></div><div className="ff-world-question" aria-live="polite"><span>ROBOT SCENARIO</span><p>{activeConcept.question}</p></div></div>
        <div className="ff-hero-bottom"><div className="ff-concept-controls"><span>EXPLORE THE CONCEPT</span><div className="ff-scenario-buttons" role="group" aria-label="Illustrative scenarios, planned capabilities">{concepts.map(item => <button key={item.id} aria-pressed={scenario === item.id} onClick={() => setScenario(item.id)}>{item.label}</button>)}{!reduced && <button className="ff-motion-button" onClick={() => setPaused(v => !v)} aria-label={paused ? 'Play illustration motion' : 'Pause illustration motion'}><span aria-hidden="true">{paused ? '▷' : 'Ⅱ'}</span></button>}</div><p>Concept illustration · Scenario capabilities shown are planned.</p></div><button className="ff-scroll-cue" onClick={() => goTo('ff-purpose')}><span>SCROLL TO EXPLORE</span><i/></button></div>
      </section>

      <section id="ff-purpose" className="ff-purpose ff-section">
        <div className="ff-section-label ff-reveal"><span>THE IDEA</span><Crosshair/></div>
        <div className="ff-purpose-body ff-reveal"><h2>Start with one<br/><em>testable question.</em></h2><div className="ff-purpose-columns"><p className="ff-large-copy">Which operating condition could push your design past its limit?</p><p>FailureForge runs simulations of supported designs, from a shelf under load to a moving robot joint. Compare a normal condition with a change you expect in use, then inspect the measurements behind each result.</p></div></div>
        <div className="ff-purpose-equation ff-reveal"><div><span>REFERENCE</span><strong>How the design normally works</strong></div><Plus/><div><span>COMPARISON</span><strong>One changed condition</strong></div><Plus/><div><span>RESULT</span><strong>The measured difference</strong></div></div>
      </section>

      <section id="ff-process" className="ff-process" ref={process} aria-labelledby="ff-process-title">
        <div className="ff-process-sticky">
          <div className="ff-process-heading"><div className="ff-section-label"><span>HOW IT WORKS</span><Crosshair/></div><h2 id="ff-process-title">Your first<br/><em>simulation.</em></h2></div>
          <div className="ff-process-art"><WorkflowVisual step={step}/><div className="ff-process-progress" aria-hidden="true" style={{ '--ff-progress': `${(step + 1) / 3 * 100}%` } as CSSProperties}/></div>
          <div className="ff-process-steps" role="group" aria-label="Investigation workflow">{steps.map((item, index) => <button className={step === index ? 'ff-process-step ff-active' : 'ff-process-step'} key={item.name} aria-pressed={step === index} onClick={() => chooseStep(index)}><span className="ff-step-name">{item.name}<span aria-hidden="true">{step === index ? '−' : '+'}</span></span><strong>{item.title}</strong><span className="ff-step-text">{item.text}</span><small>{item.detail}</small></button>)}</div>
        </div>
      </section>

      <section className="ff-scenarios ff-section" id="ff-scenarios">
        <div className="ff-scenarios-heading ff-reveal"><div className="ff-section-label"><span>ROBOT SCENARIOS</span><Crosshair/></div><h2>Change the situation.<br/><em>Ask a harder question.</em></h2><p>The robotics work explores how a change in the environment affects the robot’s task. These examples show current and planned capabilities.</p></div>
        <div className="ff-scenario-families">
          <article className="ff-family ff-reveal"><div className="ff-family-top"><span>ARRANGEMENT</span><span className="ff-tag">Planned</span></div><ScenarioGraphic kind="arrangement"/><h3>Can it still reach<br/>what matters?</h3><p>Move the object. Add clutter. Constrain the approach. Explore how the layout changes the task.</p><div className="ff-family-foot">Object positions · Obstacles · Clutter</div></article>
          <article className="ff-family ff-reveal"><div className="ff-family-top"><span>INTERACTION</span><span className="ff-tag">Planned</span></div><ScenarioGraphic kind="contact"/><h3>Will the grasp<br/>still hold?</h3><p>Change the object and its physical properties. Investigate the effects of contact, weight, and friction.</p><div className="ff-family-foot">Object properties · Grip · Contact</div></article>
          <article className="ff-family ff-reveal"><div className="ff-family-top"><span>PERCEPTION</span><span className="ff-tag ff-tag-current">First integration</span></div><ScenarioGraphic kind="perception"/><h3>What if the robot<br/>sees it differently?</h3><p>Change the robot’s camera view and the lighting. Test how altered observations affect its actions.</p><div className="ff-family-foot">Camera position · Lighting</div></article>
        </div>
        <p className="ff-scenario-note">Arrangement and interaction are product directions. The current robot integration explores perception changes in one supported task.</p>
      </section>

      <section className="ff-evidence ff-section" id="ff-evidence">
        <div className="ff-evidence-title ff-reveal"><div className="ff-section-label"><span>THE OUTPUT</span><Crosshair/></div><h2>A failure is useful<br/>when you can<br/><em>look closer.</em></h2><p>Keep the experiment with the result. Follow a case from its conditions to its outcome, then return to it with a better question.</p></div>
        <div className="ff-evidence-list ff-reveal"><article><span className="ff-evidence-icon"><Crosshair/></span><div><h3>See what happened.</h3><p>Inspect the recorded measurements for your reference and changed conditions. Open the replay to see where a shelf bent or how a joint moved.</p></div></article><article><span className="ff-evidence-icon"><span aria-hidden="true">±</span></span><div><h3>Isolate what changed.</h3><p>Check the load, model and other inputs used in each run. Try a smaller change to see when the limit is crossed.</p></div></article><article><span className="ff-evidence-icon"><span aria-hidden="true">↻</span></span><div><h3>Keep the evidence.</h3><p>Return to a saved run or export its inputs, measurements and outcome for a design review.</p></div></article><a href="#/projects" className="ff-text-link">Open my projects<Plus/></a></div>
      </section>

      <section className="ff-release ff-section" id="ff-release">
        <div className="ff-release-heading ff-reveal"><div className="ff-section-label"><span>AVAILABLE TODAY</span><Crosshair/></div><h2>Bring your<br/><em>own prototype.</em></h2><p>Start with what you have, whether it is an idea, a model file or measurements from the bench. In your project, choose the behavior you want to study and supply the inputs that model needs.</p></div>
        <div className="ff-release-details ff-reveal"><div className="ff-release-status"><span>YOUR PROJECT</span><h3>Test a supported design.</h3><p>Study joint motion, beam bending or heat flow. You can also begin with a brief and prepare the measurements your first test will need.</p><a href="#/projects/new">Start my own project<Plus/></a></div><div className="ff-release-status"><span>ROBOT BENCHMARK</span><h3>Run the bowl-placement task.</h3><p>A separate benchmark tests a Panda arm and pretrained controller. Robot-policy campaigns use a qualified execution host.</p><a href="#/settings">View runtime settings<Plus/></a></div></div>
      </section>

      <section className="ff-faq ff-section"><div className="ff-section-label ff-reveal"><span>A FEW GOOD QUESTIONS</span><Crosshair/></div><div className="ff-faq-list ff-reveal">
        <details><summary>What do I need for the shelf example?<Plus/></summary><p>The example includes the shelf dimensions, material, loads and bending limit. Open it, review the two conditions and run the simulation on your CPU. You can try it before uploading any files.</p></details>
        <details><summary>Can I test my own robot or task?<Plus/></summary><p>You can create a project for a concept, CAD design, robot model, existing simulation, or physical prototype. Attach supporting files, define model inputs, and run supported motion, calibration, beam, and heat-transfer studies in a project. The separate policy benchmark uses one supported robot, task, and controller.</p></details>
        <details><summary>Is FailureForge training the robot?<Plus/></summary><p>FailureForge evaluates an existing controller—the software that decides how the robot acts. It searches for failures and packages evidence for investigation. It does not currently train or repair the controller.</p></details>
        <details><summary>Where can I replay a test?<Plus/></summary><p>This page uses illustrations. In Projects, choose View replays to play saved motion, inspect a beam or temperature field, or explore measured samples. In Campaigns, select a tested condition to see its recorded result. Bowl-placement benchmark episodes with saved footage also have main- and wrist-camera video.</p></details>
        <details><summary>Does a simulation prove a robot is safe?<Plus/></summary><p>Simulation helps discover and investigate failures inside a defined test domain. Its results depend on the model, controller, environment, and conditions tested. They do not certify real-world robot safety.</p></details>
      </div></section>

      <section className="ff-final"><div className="ff-final-grid" aria-hidden="true"/><h2 className="ff-reveal">Run your first<br/><em>comparison.</em></h2><div className="ff-final-bottom"><p>See how a shelf responds when its load moves to the edge.</p><div className="ff-final-actions"><a className="ff-button ff-button-dark" href={shelfExampleHref}>Try the shelf example<Plus/></a><a className="ff-text-button" href="#/projects/new">Start my own project<span className="ff-small-square"/></a></div></div></section>
    </main>
    <footer className="ff-footer"><a className="ff-brand" href="#/" aria-label="FailureForge home" onClick={e => { e.preventDefault(); window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' }); }}><ForgeMark/><span>FailureForge</span></a><p>Robot behavior. Under investigation.</p><div><a href="#/settings">Settings</a><button onClick={() => window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' })}>Back to top</button></div><span className="ff-footer-bottom">SIMULATED WORLDS. BETTER QUESTIONS.</span></footer>
  </div>;
}
