/** 화면 곳곳에서 쓰는 작은 조각들. */
import { formatPercent } from '../api'

/** UIUX 문서 §5 의 4단계 색상 코딩. 판정 경로와 1:1 로 맞춘다. */
const PATH_STYLE = {
  AUTO_PASS: { label: 'AI 자동 통과', className: 'bg-pass/15 text-pass border-pass/40' },
  RULE_BASE_NONE: { label: '규칙 확정 · 정상', className: 'bg-brand/15 text-brand border-brand/40' },
  RULE_BASE_NEAR_FULL: {
    label: '규칙 확정 · Near-full',
    className: 'bg-brand/15 text-brand border-brand/40',
  },
  REVIEW_NEEDED: { label: '검토 필요', className: 'bg-danger/15 text-danger border-danger/40' },
}

export function DecisionBadge({ path }) {
  const style = PATH_STYLE[path] || {
    label: path,
    className: 'bg-muted/15 text-muted border-muted/40',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${style.className}`}
    >
      {style.label}
    </span>
  )
}

export function ReviewedBadge() {
  return (
    <span className="inline-flex items-center rounded-full border border-pass/40 bg-pass/15 px-2.5 py-0.5 text-xs font-medium text-pass">
      검토 완료
    </span>
  )
}

/**
 * 확률 막대. UIUX 문서의 "1순위 빨강 강조 / 2순위 회색" 을 따른다.
 * 숫자만 있으면 스캔이 느려서 길이로도 읽히게 한다.
 */
export function ProbabilityBar({ label, value, emphasis = false }) {
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-sm">
        <span className={emphasis ? 'font-semibold text-ink' : 'text-muted'}>{label}</span>
        <span className={`tabular-nums ${emphasis ? 'font-semibold text-ink' : 'text-muted'}`}>
          {formatPercent(value)}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-line">
        <div
          className={`h-full rounded-full transition-all ${emphasis ? 'bg-danger' : 'bg-muted'}`}
          style={{ width: `${Math.max(value * 100, 1.5)}%` }}
        />
      </div>
    </div>
  )
}

export function KpiCard({ label, value, hint, tone = 'ink', onClick }) {
  const toneClass = {
    ink: 'text-ink',
    pass: 'text-pass',
    brand: 'text-brand',
    danger: 'text-danger',
  }[tone]

  const interactive = typeof onClick === 'function'
  return (
    <div
      onClick={onClick}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={interactive ? (event) => event.key === 'Enter' && onClick() : undefined}
      className={`rounded-xl border border-line bg-panel p-4 ${
        interactive ? 'cursor-pointer transition-colors hover:border-brand/60' : ''
      }`}
    >
      <p className="text-sm text-muted">{label}</p>
      <p className={`mt-1 text-3xl font-semibold tabular-nums ${toneClass}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  )
}

export function Spinner({ label = '불러오는 중' }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-brand" />
      {label}
    </div>
  )
}

export function ErrorNote({ children, onRetry }) {
  if (!children) return null
  return (
    <div className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
      {children}
      {onRetry && (
        <button onClick={onRetry} className="ml-3 underline underline-offset-2">
          다시 시도
        </button>
      )}
    </div>
  )
}

export function EmptyNote({ children }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-6 py-12 text-center text-sm text-muted">
      {children}
    </div>
  )
}
