import { useEffect, useRef, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

interface Props {
  label: string
  active?: boolean
  count?: number
  children: ReactNode
  open: boolean
  onToggle: () => void
  onClose: () => void
  align?: 'left' | 'right'
}

export function FilterPill({ label, active, count, children, open, onToggle, onClose, align = 'left' }: Props) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open, onClose])

  return (
    <div className="fpill" ref={ref}>
      <button className={active ? 'active' : ''} onClick={onToggle}>
        {label}
        {count ? (
          <span className="badge">{count}</span>
        ) : (
          <ChevronDown size={12} style={{ opacity: 0.5 }} />
        )}
      </button>
      {open && (
        <div
          className="fpopover"
          style={align === 'right' ? { left: 'auto', right: 0 } : undefined}
        >
          {children}
        </div>
      )}
    </div>
  )
}

/* Reusable pieces inside a popover */

export function PopLabel({ children }: { children: ReactNode }) {
  return <div className="pop-label">{children}</div>
}

export function PopToggle({
  label, checked, onChange,
}: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="pop-toggle-row">
      <span>{label}</span>
      <label className="pop-toggle">
        <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
        <div className="pop-toggle-track" />
        <div className="pop-toggle-thumb" />
      </label>
    </div>
  )
}

export function PopSlider({
  label, value, min, max, step, format, onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  format?: (v: number) => string
  onChange: (v: number) => void
}) {
  const fmt = format ?? ((v: number) => String(v))
  return (
    <div className="pop-slider">
      <div className="pop-label">{label}</div>
      <input
        type="range"
        min={min} max={max} step={step} value={value}
        onChange={e => onChange(+e.target.value)}
      />
      <div className="pop-slider-vals">
        <span>{fmt(min)}</span>
        <b>{value === min ? 'Tous' : fmt(value)}</b>
        <span>{fmt(max)}</span>
      </div>
    </div>
  )
}

export function PopCheckRow({
  label, checked, count, onChange,
}: { label: string; checked: boolean; count?: number; onChange: () => void }) {
  return (
    <div className="pop-row" onClick={onChange}>
      <span className={`pop-check ${checked ? 'on' : ''}`}>
        {checked && (
          <svg width="9" height="7" viewBox="0 0 9 7" fill="none">
            <path d="M1 3.5L3.5 6L8 1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </span>
      <span style={{ flex: 1 }}>{label}</span>
      {count != null && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-faint)' }}>{count}</span>}
    </div>
  )
}
