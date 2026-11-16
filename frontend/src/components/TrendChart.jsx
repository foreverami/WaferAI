/**
 * 주별 판정 추이 — UIUX 화면 5 의 성능 추이 그래프.
 *
 * 막대: 그 주에 올라온 웨이퍼를 처리 경로별로 쌓는다(자동 통과 · 규칙 확정 · 검토 · 판정 불가).
 * 선: 사람이 검토한 건 중 AI 최종 판정과 같았던 비율(오른쪽 축). 검토가 없는 주는 점을 찍지 않는다.
 * 외부 차트 라이브러리 없이 SVG 로 그린다 — CSP 가 'self' 만 허용하고, 막대 몇 개에 의존성을 들일 일이 아니다.
 */
const SERIES = [
  { key: 'auto_pass', label: 'AI 자동 통과', className: 'fill-pass' },
  { key: 'rule_base', label: '규칙 확정', className: 'fill-brand' },
  { key: 'review_needed', label: '검토 필요', className: 'fill-danger' },
  { key: 'out_of_scope', label: '판정 불가', className: 'fill-warn' },
]

const WIDTH = 720
const HEIGHT = 220
const PAD = { top: 16, right: 44, bottom: 30, left: 40 }

export default function TrendChart({ weeks }) {
  const innerW = WIDTH - PAD.left - PAD.right
  const innerH = HEIGHT - PAD.top - PAD.bottom
  const maxUploads = Math.max(1, ...weeks.map((week) => week.uploads))
  const slot = innerW / Math.max(weeks.length, 1)
  const barW = Math.min(36, slot * 0.6)
  const y = (count) => PAD.top + innerH - (count / maxUploads) * innerH
  const yRate = (rate) => PAD.top + innerH - rate * innerH

  const points = weeks
    .map((week, index) => ({ index, week }))
    .filter(({ week }) => week.reviewed > 0)
    .map(({ index, week }) => ({
      x: PAD.left + slot * index + slot / 2,
      y: yRate(week.ai_agreed / week.reviewed),
      week,
    }))

  return (
    <div className="space-y-2">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full" role="img" aria-label="주별 판정 경로와 AI 일치율">
        {[0, 0.5, 1].map((tick) => (
          <g key={tick}>
            <line x1={PAD.left} x2={WIDTH - PAD.right} y1={yRate(tick)} y2={yRate(tick)}
                  className="stroke-line" strokeDasharray="3 4" />
            <text x={PAD.left - 6} y={yRate(tick) + 4} textAnchor="end" className="fill-muted text-[10px]">
              {Math.round(maxUploads * tick)}
            </text>
            <text x={WIDTH - PAD.right + 6} y={yRate(tick) + 4} className="fill-muted text-[10px]">
              {Math.round(tick * 100)}%
            </text>
          </g>
        ))}

        {weeks.map((week, index) => {
          const x = PAD.left + slot * index + (slot - barW) / 2
          let base = 0
          return (
            <g key={week.week}>
              {SERIES.map((series) => {
                const value = week[series.key]
                if (!value) return null
                const top = y(base + value)
                const rect = (
                  <rect key={series.key} x={x} y={top} width={barW} height={y(base) - top}
                        className={series.className} opacity="0.75">
                    <title>{`${week.week} 주 · ${series.label} ${value}건`}</title>
                  </rect>
                )
                base += value
                return rect
              })}
              <text x={x + barW / 2} y={HEIGHT - 10} textAnchor="middle" className="fill-muted text-[10px]">
                {week.week.slice(5)}
              </text>
            </g>
          )
        })}

        {points.length > 1 && (
          <polyline points={points.map((p) => `${p.x},${p.y}`).join(' ')}
                    className="fill-none stroke-ink" strokeWidth="2" />
        )}
        {points.map((p) => (
          <circle key={p.week.week} cx={p.x} cy={p.y} r="3.5" className="fill-ink">
            <title>{`${p.week.week} 주 · 검토 ${p.week.reviewed}건 중 AI 일치 ${p.week.ai_agreed}건`}</title>
          </circle>
        ))}
      </svg>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {SERIES.map((series) => (
          <span key={series.key} className="inline-flex items-center gap-1.5">
            <svg width="10" height="10" aria-hidden="true"><rect width="10" height="10" className={series.className} opacity="0.75" /></svg>
            {series.label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <svg width="14" height="10" aria-hidden="true"><line x1="0" x2="14" y1="5" y2="5" className="stroke-ink" strokeWidth="2" /></svg>
          검토 결과와 AI 판정 일치율 (오른쪽 축)
        </span>
      </div>
    </div>
  )
}
