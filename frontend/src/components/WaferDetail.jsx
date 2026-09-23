/**
 * 웨이퍼 상세 팝업 — UIUX 문서 화면 2·4.
 *
 * 좌측은 XAI 시각화(원본 / 히트맵 / 겹쳐보기 토글), 우측은 의사결정 워크플로.
 * 버튼 크기를 빈도 순으로 줬다: 1순위 승인(큰 버튼) → 2순위 수정(링크) →
 * 수동 라벨링(드롭다운).
 */
import { useEffect, useState } from 'react'

import { api, formatPercent, formatTime, ranked } from '../api'
import WaferMap from './WaferMap'
import { DecisionBadge, ErrorNote, ProbabilityBar, Spinner } from './ui'

const VIEWS = [
  { key: 'original', label: '원본' },
  { key: 'heatmap', label: '히트맵' },
  { key: 'overlay', label: '겹쳐보기' },
]

export default function WaferDetail({ waferId, onClose, onReviewed }) {
  const [wafer, setWafer] = useState(null)
  const [error, setError] = useState(null)
  const [view, setView] = useState('overlay')
  const [busy, setBusy] = useState(false)
  // 'loading' | 'ready' | 'error' — 히트맵 이미지 적재 상태
  const [heatmap, setHeatmap] = useState('loading')
  // 재시도 횟수. URL 에 실어야 브라우저가 실패한 응답을 캐시에서 꺼내지 않는다.
  const [attempt, setAttempt] = useState(0)
  const [manualLabel, setManualLabel] = useState('')
  const [memo, setMemo] = useState('')

  useEffect(() => {
    let cancelled = false
    setWafer(null)
    setError(null)
    setHeatmap('loading')
    setAttempt(0)
    api
      .record(waferId)
      .then((data) => !cancelled && setWafer(data))
      .catch((caught) => !cancelled && setError(caught.detail || '기록을 불러오지 못했습니다'))
    return () => {
      cancelled = true
    }
  }, [waferId])

  // Esc 로 닫기. 모달을 키보드로 빠져나올 수 없으면 연속 처리가 느려진다.
  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const act = async (operation) => {
    setBusy(true)
    setError(null)
    try {
      const updated = await operation()
      setWafer(updated)
      onReviewed?.(updated)
    } catch (caught) {
      setError(caught.detail || '처리에 실패했습니다')
    } finally {
      setBusy(false)
    }
  }

  const order = wafer ? ranked(wafer.probabilities) : []
  const [first, second] = order
  const reviewed = wafer?.reviews?.length > 0

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-full w-full max-w-5xl overflow-y-auto rounded-2xl border border-line bg-surface p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">웨이퍼 상세 분석</h2>
            <p className="font-mono text-xs text-muted">{waferId}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted hover:text-ink"
          >
            닫기
          </button>
        </div>

        <ErrorNote>{error}</ErrorNote>
        {!wafer && !error && <Spinner />}

        {wafer && (
          <div className="grid gap-6 md:grid-cols-2">
            {/* 좌: XAI 시각화 */}
            <div>
              <div className="mb-3 inline-flex rounded-lg border border-line p-0.5">
                {VIEWS.map((option) => (
                  <button
                    key={option.key}
                    onClick={() => setView(option.key)}
                    className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                      view === option.key ? 'bg-brand text-white' : 'text-muted hover:text-ink'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              <div className="relative overflow-hidden rounded-lg bg-black">
                {/* 원본은 항상 렌더링해 박스 높이를 잡는다. 히트맵만 볼 때는 감추기만 한다.
                    빼버리면 히트맵이 오기 전까지 높이가 0이라 화면이 튄다. */}
                <div className={view === 'heatmap' ? 'invisible' : ''}>
                  <WaferMap map={wafer.wafer_map} />
                </div>

                {view !== 'original' && (
                  <img
                    src={api.heatmapUrl(waferId, null, attempt)}
                    alt="Grad-CAM 히트맵"
                    onLoad={() => setHeatmap('ready')}
                    onError={() => setHeatmap('error')}
                    className={`wafer-image absolute inset-0 w-full transition-opacity duration-300 ${
                      heatmap !== 'ready' ? 'opacity-0' : view === 'overlay' ? 'opacity-85' : ''
                    }`}
                  />
                )}

                {/* 히트맵은 지연 생성이라 첫 요청에서 모델 로딩과 역전파가 함께 일어난다.
                    몇 초가 걸리는데 표시가 없으면 고장난 것처럼 보인다. */}
                {view !== 'original' && heatmap === 'loading' && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/70">
                    <span className="h-7 w-7 animate-spin rounded-full border-2 border-line border-t-brand" />
                    <p className="text-xs text-muted">히트맵 생성 중…</p>
                    <p className="text-[11px] text-muted/70">처음 한 번은 몇 초 걸립니다</p>
                  </div>
                )}

                {view !== 'original' && heatmap === 'error' && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/70 px-6 text-center">
                    <p className="text-xs text-danger">히트맵을 생성하지 못했습니다</p>
                    <button
                      onClick={() => {
                        setHeatmap('loading')
                        setAttempt((count) => count + 1)
                      }}
                      className="text-xs text-brand underline underline-offset-2"
                    >
                      다시 시도
                    </button>
                  </div>
                )}
              </div>
              <p className="mt-2 text-xs text-muted">
                붉은 영역이 AI 가 판단 근거로 삼은 곳입니다 (Grad-CAM).
              </p>

              <dl className="mt-4 space-y-1.5 text-xs text-muted">
                <div className="flex justify-between">
                  <dt>결함 밀도</dt>
                  <dd className="tabular-nums text-ink">{formatPercent(wafer.defect_ratio, 2)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>입력 형식</dt>
                  <dd className="text-ink">
                    {wafer.input_type === 'image' ? '렌더링 이미지' : '웨이퍼 맵 데이터'}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt>처리 시각</dt>
                  <dd className="text-ink">{formatTime(wafer.processed_at)}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt>모델 버전</dt>
                  <dd className="truncate font-mono text-ink">
                    {wafer.model_version?.slice(0, 12) || '-'}
                  </dd>
                </div>
              </dl>

              {wafer.input_info?.warnings?.length > 0 && (
                <div className="mt-3 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
                  {wafer.input_info.warnings.map((warning) => (
                    <p key={warning}>{warning}</p>
                  ))}
                </div>
              )}
            </div>

            {/* 우: 의사결정 워크플로 */}
            <div className="space-y-5">
              <div className="flex items-center gap-2">
                <DecisionBadge path={wafer.decision_path} />
                {reviewed && (
                  <span className="text-xs text-muted">
                    최종 확정: <strong className="text-ink">{wafer.reviews[0].final_class}</strong>
                  </span>
                )}
              </div>

              <div className="space-y-3">
                {first && <ProbabilityBar label={`1순위 · ${first[0]}`} value={first[1]} emphasis />}
                {second && <ProbabilityBar label={`2순위 · ${second[0]}`} value={second[1]} />}
              </div>

              <div className="space-y-3 border-t border-line pt-5">
                <button
                  onClick={() => act(() => api.approve(waferId, 1, memo))}
                  disabled={busy || !first}
                  className="w-full rounded-lg bg-pass px-4 py-3 text-sm font-semibold text-surface transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  1순위 승인 · {first?.[0]}
                </button>

                {second && (
                  <button
                    onClick={() => act(() => api.approve(waferId, 2, memo))}
                    disabled={busy}
                    className="w-full text-sm text-brand underline underline-offset-2 disabled:opacity-40"
                  >
                    2순위로 수정 · {second[0]}
                  </button>
                )}

                <div className="flex gap-2">
                  <select
                    value={manualLabel}
                    onChange={(event) => setManualLabel(event.target.value)}
                    className="flex-1 rounded-lg border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-brand"
                  >
                    <option value="">수동 라벨링…</option>
                    {order.map(([name]) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => act(() => api.review(waferId, manualLabel, memo))}
                    disabled={busy || !manualLabel}
                    className="rounded-lg border border-line px-4 py-2 text-sm transition-colors hover:border-brand disabled:opacity-40"
                  >
                    확정
                  </button>
                </div>

                <textarea
                  value={memo}
                  onChange={(event) => setMemo(event.target.value)}
                  placeholder="검토 메모 (선택)"
                  rows={2}
                  className="w-full resize-none rounded-lg border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-brand"
                />
              </div>

              {reviewed && (
                <div className="border-t border-line pt-4">
                  <p className="mb-2 text-xs text-muted">검토 이력</p>
                  <ul className="space-y-2">
                    {wafer.reviews.map((review) => (
                      <li key={review.review_id} className="text-xs">
                        <span className="font-medium text-ink">{review.final_class}</span>
                        <span className="text-muted">
                          {' · '}
                          {review.reviewer_id} · {formatTime(review.reviewed_at)}
                        </span>
                        {review.review_memo && (
                          <p className="mt-0.5 text-muted">{review.review_memo}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
