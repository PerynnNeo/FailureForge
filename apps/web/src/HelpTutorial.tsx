import { useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from './components';
import './helpTutorial.css';

export type TutorialStep = { target: string; title: string; body: string; action?: string; example?: string };

type Props = {
  title: string;
  steps: readonly TutorialStep[];
  initialStep?: number;
  onStepChange?: (step: TutorialStep, index: number) => void;
};

function findTarget(root: HTMLElement, name: string) {
  return Array.from(root.querySelectorAll<HTMLElement>(`[data-tour="${CSS.escape(name)}"]`))
    .find(node => node.getClientRects().length && getComputedStyle(node).visibility === 'visible');
}

function reveal(node: HTMLElement) {
  const area = node.closest('.campaign-dialog form') ?? document.getElementById('root');
  const fits = node.offsetHeight + 40 < (area?.clientHeight ?? window.innerHeight);
  node.scrollIntoView({ block: fits ? 'center' : 'start', inline: 'nearest', behavior: 'instant' });
}

function mark(node: HTMLElement, description: string) {
  node.setAttribute('data-tour-current', '');
  const ids = (node.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
  node.setAttribute('aria-describedby', [...ids, description].join(' '));
  return () => {
    node.removeAttribute('data-tour-current');
    const remaining = (node.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(id => id && id !== description);
    if (remaining.length) node.setAttribute('aria-describedby', remaining.join(' '));
    else node.removeAttribute('aria-describedby');
  };
}

export function HelpTutorial({ title, steps, initialStep = 0, onStepChange }: Props) {
  const id = useId();
  const descriptionId = id + '-description';
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const topics = useRef<HTMLSelectElement>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [selected, setSelected] = useState('');
  const [highlighted, setHighlighted] = useState<HTMLElement | null>(null);
  const entry = Math.max(0, Math.min(initialStep, steps.length - 1));
  const selectedIndex = steps.findIndex(item => item.target === selected);
  const index = selectedIndex < 0 ? entry : selectedIndex;
  const step = steps[index];
  const target = step?.target;
  const entryTarget = useRef('');
  entryTarget.current = steps[entry]?.target ?? '';
  const keepPosition = useRef(false);

  function select(next: number) {
    const topic = steps[next];
    if (!topic) return;
    setSelected(topic.target);
    onStepChange?.(topic, next);
  }

  function close() {
    keepPosition.current = true;
    if (panel.current?.contains(document.activeElement)) trigger.current?.focus({ preventScroll: true });
    setHost(null);
  }

  function open() {
    if (host) { close(); return; }
    keepPosition.current = false;
    select(entry);
    setHost(trigger.current?.closest<HTMLDialogElement>('dialog[open]') ?? document.body);
  }

  // Give the work area and the guide separate space, including in the campaign editor.
  useLayoutEffect(() => {
    if (!host) return;
    const isPage = host === document.body;
    const scroller = isPage ? document.getElementById('root') : host.querySelector('form');
    const before = isPage ? window.scrollY : host.scrollTop;
    host.classList.add('has-help-tour');
    if (scroller) scroller.scrollTop = before;
    topics.current?.focus({ preventScroll: true });
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || host !== (document.querySelector('dialog:modal') ?? document.body)) return;
      event.preventDefault();
      event.stopPropagation();
      close();
    };
    document.addEventListener('keydown', escape, true);
    const resize = new ResizeObserver(() => {
      if (isPage && panel.current) host.style.setProperty('--help-tour-height', panel.current.offsetHeight + 'px');
    });
    if (panel.current) resize.observe(panel.current);
    return () => {
      document.removeEventListener('keydown', escape, true);
      resize.disconnect();
      const after = scroller?.scrollTop ?? before;
      host.classList.remove('has-help-tour');
      host.style.removeProperty('--help-tour-height');
      if (keepPosition.current) {
        if (isPage) window.scrollTo({ top: after, behavior: 'instant' });
        else host.scrollTop = after;
      }
    };
  }, [host]);

  useLayoutEffect(() => {
    if (!host || !target) return;
    const root = host === document.body ? document.getElementById('root')! : host;
    let current: HTMLElement | undefined;
    let unmark: (() => void) | undefined;
    let frame = 0;
    function sync() {
      if (host === document.body && document.querySelector('dialog:modal')) {
        setHost(null);
        return;
      }
      const next = findTarget(root, target!);
      if (current && !next && entryTarget.current !== target && findTarget(root, entryTarget.current)) {
        // The user changed pages within the wizard or switched tabs while reading.
        setSelected(entryTarget.current);
      }
      if (current === next) return;
      unmark?.();
      current = next;
      setHighlighted(next ?? null);
      if (next) {
        unmark = mark(next, descriptionId);
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => { if (next.isConnected) reveal(next); });
      }
    }
    setHighlighted(null);
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-tour', 'hidden', 'open'] });
    return () => { observer.disconnect(); cancelAnimationFrame(frame); unmark?.(); };
  }, [host, target, descriptionId]);

  function goToSection() {
    if (!highlighted) { select(index); return; }
    reveal(highlighted);
    const selector = 'button:enabled, a[href], input:enabled, select:enabled, textarea:enabled, summary, [tabindex="0"]';
    const control = highlighted.matches(selector) ? highlighted : highlighted.querySelector<HTMLElement>(selector);
    if (control) control.focus({ preventScroll: true });
    else {
      if (!highlighted.hasAttribute('tabindex')) {
        highlighted.tabIndex = -1;
        highlighted.addEventListener('blur', () => highlighted.removeAttribute('tabindex'), { once: true });
      }
      highlighted.focus({ preventScroll: true });
    }
  }

  if (!step) return null;
  return <>
    <button ref={trigger} type="button" className="button secondary help-tutorial-trigger" onClick={open}
      aria-expanded={!!host} aria-controls={host ? id : undefined} aria-label={title} title={title}>
      <Icon name="help" size={19}/>Tutorial
    </button>
    {host && createPortal(<section ref={panel} id={id} className="help-tour" aria-label={title}>
      <div className="help-tour-inner">
        <header className="help-tour-header">
          <span><Icon name="help" size={18}/>{title}</span>
          <span className="help-tour-count">Step {index + 1} of {steps.length}</span>
          <button type="button" className="icon-button" aria-label="Close tutorial" onClick={close}><Icon name="close" size={18}/></button>
        </header>
        <div className="help-tour-main">
          <select ref={topics} value={target} aria-label="Tutorial topic" onChange={event => select(event.target.selectedIndex)}>
            {steps.map(topic => <option key={topic.target} value={topic.target}>{topic.title}</option>)}
          </select>
          <div id={descriptionId} className="help-tour-copy" aria-live="polite" aria-atomic="true">
            <span className="sr-only">{step.title}. </span>
            {highlighted ? <><p>{step.body}</p>{step.action && <p>{step.action}</p>}{step.example && <p><strong>Example</strong> {step.example}</p>}</>
              : <p>Waiting for this section to appear. You can also choose another topic.</p>}
          </div>
        </div>
        <footer className="help-tour-footer">
          <button type="button" className="help-tour-show" onClick={goToSection}>Show section</button>
          <button type="button" className="button secondary" disabled={index === 0} onClick={() => select(index - 1)}>Previous</button>
          <button type="button" className="button primary" onClick={() => index + 1 < steps.length ? select(index + 1) : close()}>
            {index + 1 < steps.length ? <>Next<Icon name="chevron" size={15}/></> : 'Done'}
          </button>
        </footer>
      </div>
    </section>, host)}
  </>;
}
