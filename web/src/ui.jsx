export const fmt = (n) => (n == null ? '–' : n.toLocaleString(undefined, { maximumFractionDigits: 1 }))
export const pct = (x) => (x == null ? '–' : `${Math.round(x * 100)}%`)

const LABEL_CLASS = {
  consistent: 'label-ok',
  'insufficient data': 'label-unknown',
  'review recommended': 'label-review',
}

export function Label({ value }) {
  return <span className={`label ${LABEL_CLASS[value] ?? ''}`}>{value}</span>
}
