type Props = { status: string | null | undefined }

function colorFor(status: string) {
  const s = status.toUpperCase()
  if (s === 'PASSED') return { bg: '#ECFDF3', fg: '#027A48', bd: '#ABEFC6' }
  if (s === 'FAILED') return { bg: '#FEF3F2', fg: '#B42318', bd: '#FECDCA' }
  if (s === 'RUNNING') return { bg: '#EFF8FF', fg: '#175CD3', bd: '#B2DDFF' }
  if (s === 'QUEUED') return { bg: '#F9FAFB', fg: '#344054', bd: '#EAECF0' }
  return { bg: '#F2F4F7', fg: '#344054', bd: '#D0D5DD' }
}

export function StatusChip({ status }: Props) {
  const v = status || '-'
  const c = colorFor(v)
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        borderRadius: 999,
        padding: '2px 10px',
        fontSize: 12,
        border: `1px solid ${c.bd}`,
        background: c.bg,
        color: c.fg,
        fontWeight: 600,
      }}
    >
      {v}
    </span>
  )
}


