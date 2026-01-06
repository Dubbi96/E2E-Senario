import type { ReactNode } from 'react'

export function Card({
  title,
  right,
  children,
}: {
  title?: ReactNode
  right?: ReactNode
  children?: ReactNode
}) {
  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 14,
        padding: 12,
        background: 'var(--panel)',
      }}
    >
      {(title || right) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <div style={{ fontWeight: 800 }}>{title}</div>
          <div style={{ marginLeft: 'auto' }}>{right}</div>
        </div>
      )}
      {children}
    </div>
  )
}

export function KV({
  label,
  value,
}: {
  label: ReactNode
  value: ReactNode
}) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: 8, padding: '4px 0' }}>
      <div style={{ color: 'var(--muted)', fontWeight: 700, fontSize: 12 }}>{label}</div>
      <div style={{ fontFamily: 'inherit' }}>{value}</div>
    </div>
  )
}


