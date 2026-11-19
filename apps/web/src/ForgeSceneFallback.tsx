import { useId } from 'react'

/** A static, decorative substitute for devices without WebGL. */
export default function ForgeSceneFallback({ scenario = 'placement' }: { scenario?: 'placement' | 'obstacles' | 'grip' }) {
  const id = useId().replace(/:/g, '')
  return (
    <svg viewBox="0 0 700 600" width="100%" height="100%" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id={`${id}-body`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#e1ebe3" /><stop offset=".5" stopColor="#94a99b" /><stop offset="1" stopColor="#30493a" />
        </linearGradient>
        <linearGradient id={`${id}-dark`} x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#465e4d" /><stop offset="1" stopColor="#0a140e" />
        </linearGradient>
        <radialGradient id={`${id}-shadow`}><stop stopColor="#000" stopOpacity=".8" /><stop offset="1" stopColor="#000" stopOpacity="0" /></radialGradient>
        <linearGradient id={`${id}-orange`} x1="0" y1="0" x2="1" y2="1"><stop stopColor="#ffb17c" /><stop offset=".5" stopColor="#fc6b32" /><stop offset="1" stopColor="#a53314" /></linearGradient>
      </defs>
      <ellipse cx="358" cy="472" rx="270" ry="76" fill={`url(#${id}-shadow)`} />
      <path d="M126 397 381 321 585 410 330 496Z" fill="#2c4032" stroke="#4b6753" />
      <path d="M126 397v17l204 89v-7Zm204 99 255-86v17l-255 87Z" fill={`url(#${id}-dark)`} />
      <path d="m153 400 228-67 175 77-227 76Z" fill="#24372b" />
      <path d="m430 470 92-32" stroke="#f78343" strokeWidth="3" />
      <ellipse cx="277" cy="408" rx="62" ry="24" fill={`url(#${id}-dark)`} />
      <path d="M223 365v37c0 29 108 29 108 0v-37Z" fill={`url(#${id}-body)`} />
      <ellipse cx="277" cy="365" rx="54" ry="22" fill="#8ea696" />
      <path d="m277 359-28-139" stroke={`url(#${id}-dark)`} strokeWidth="67" strokeLinecap="round" />
      <path d="m274 337-21-104" stroke={`url(#${id}-body)`} strokeWidth="58" strokeLinecap="round" />
      <path d="m249 218 144-56" stroke={`url(#${id}-dark)`} strokeWidth="62" strokeLinecap="round" />
      <path d="m272 209 99-39" stroke={`url(#${id}-body)`} strokeWidth="55" strokeLinecap="round" />
      <ellipse cx="248" cy="219" rx="30" ry="35" transform="rotate(-20 248 219)" fill={`url(#${id}-dark)`} />
      <ellipse cx="243" cy="216" rx="17" ry="23" transform="rotate(-20 243 216)" fill="#839f90" />
      <path d="m394 163 52 99" stroke={`url(#${id}-dark)`} strokeWidth="47" strokeLinecap="round" />
      <path d="m404 182 31 60" stroke={`url(#${id}-body)`} strokeWidth="42" strokeLinecap="round" />
      <ellipse cx="390" cy="164" rx="27" ry="31" transform="rotate(-25 390 164)" fill={`url(#${id}-dark)`} />
      <ellipse cx="386" cy="160" rx="15" ry="20" transform="rotate(-25 386 160)" fill="#9cb3a4" />
      <path d="m444 264 13 35" stroke="#ea582a" strokeWidth="25" />
      <path d="m450 294-12 18 8 21m18-32 22 11-1 18" fill="none" stroke="#718d7a" strokeWidth="11" strokeLinejoin="round" />
      {scenario === 'placement' && <g fill="none" stroke="#a7c3af" strokeWidth="1.1" strokeDasharray="4 5" opacity=".65">
        <path d="m417 377 31-11 30 13-31 12Zm0 0v35l30 14 31-12v-35m-31 12v35" />
        <path d="M445 364c6-46 57-64 73-26" stroke="#ff955c" />
      </g>}
      {scenario !== 'grip' && <g transform={scenario === 'placement' ? 'translate(55 -22)' : undefined}>
        <path d="m417 377 31-11 30 13-31 12Z" fill="#ffb17b" />
        <path d="m417 377 30 14v35l-30-14Z" fill="#f17639" />
        <path d="m447 391 31-12v35l-31 12Z" fill="#b8411c" />
        <path d="m432 377 15-5 14 6-15 5Z" fill="#293c2f" />
      </g>}
      {scenario === 'obstacles' && <g>
        <path d="m498 333 13-5 9 4v97l-22 8Z" fill="#45634f" />
        <path d="m520 332 57 26v95l-57-24Z" fill="#16291c" />
        <path d="m498 333 22-8 57 26v8l-57-25-22 8Z" fill="#ef7a37" />
        <path d="m534 368 12 5m-12 18 12 5m-12 18 12 5" stroke="#f38a48" strokeWidth="5" />
        <path d="M462 355c-13-79 58-88 77-42" fill="none" stroke="#ff9a5e" strokeWidth="1.7" strokeDasharray="4 5" />
      </g>}
      {scenario === 'grip' && <g>
        <circle cx="462" cy="369" r="28" fill={`url(#${id}-orange)`} />
        <ellipse cx="462" cy="369" rx="28" ry="9" transform="rotate(30 462 369)" fill="none" stroke="#273b2c" strokeWidth="5" />
        <path d="M486 376c16 12 24 30 33 49" fill="none" stroke="#ff9a5e" strokeWidth="1.7" strokeDasharray="4 5" />
        <ellipse cx="521" cy="430" rx="22" ry="9" fill="none" stroke="#f88b48" />
      </g>}
    </svg>
  )
}
