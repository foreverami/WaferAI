/**
 * 설정 — UIUX 문서 화면 6·7의 임계값 슬라이더.
 * 수석 엔지니어 이상만 들어온다(서버에서도 막는다).
 */
import { useEffect, useState } from 'react'

import { api, formatPercent, formatTime } from '../api'
import { ErrorNote, Spinner } from '../components/ui'

// 모델에 확신도 프로필이 없을 때(1학기 모델)의 슬라이더 상한
const CONFIDENCE_CEILING = 0.99
// 이 비율이 넘는 웨이퍼가 검토로 가면 대기열이 감당하기 어렵다고 보고 경고한다
const REVIEW_WARN = 0.2
const REVIEW_DANGER = 0.5

/**
 * 임계값을 이 값으로 두면 테스트 셋에서 검토로 갔을 비율.
 * 곡선은 0.01 간격이라 바로 아래 눈금의 값을 쓴다. 최대 확신도보다 높으면 전부 검토다.
 */
function reviewRateAt(profile, confidence) {
  if (!profile) return null
  if (confidence > profile.confidence_max) return 1
  let rate = 0
  for (const [threshold, value] of profile.review_curve) {
    if (threshold > confidence + 1e-9) break
    rate = value
  }
  return rate
}

export default function Settings() {
  const [values, setValues] = useState(null)
  const [meta, setMeta] = useState(null)
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .thresholds()
      .then(({ updated_at, updated_by, confidence_profile, ...rest }) => {
        setValues(rest)
        setMeta({ updated_at, updated_by })
        setProfile(confidence_profile)
      })
      .catch((caught) => setError(caught.detail || '설정을 불러오지 못했습니다'))
  }, [])

  const update = (patch) => {
    setValues((current) => ({ ...current, ...patch }))
    setSaved(false)
  }

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const { updated_at, updated_by, confidence_profile, ...rest } = await api.saveThresholds(values)
      setValues(rest)
      setMeta({ updated_at, updated_by })
      setProfile(confidence_profile)
      setSaved(true)
    } catch (caught) {
      setError(caught.detail || '저장에 실패했습니다')
    } finally {
      setBusy(false)
    }
  }

  if (!values) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-semibold">설정</h2>
        <ErrorNote>{error}</ErrorNote>
        {!error && <Spinner />}
      </div>
    )
  }

  const confidenceMax = profile
    ? Math.floor(profile.confidence_max * 100) / 100
    : CONFIDENCE_CEILING
  const reviewRate = reviewRateAt(profile, values.confidence)

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold">판정 임계값</h2>
        <p className="text-sm text-muted">
          생산성과 품질의 균형을 조절합니다. 바꾸면 이후 분석부터 바로 적용됩니다.
        </p>
      </div>

      <ErrorNote>{error}</ErrorNote>

      <div className="space-y-6 rounded-xl border border-line bg-panel p-5">
        <div>
          <div className="mb-2 flex items-baseline justify-between">
            <label htmlFor="confidence" className="text-sm font-medium">
              AI 확신도 임계값
            </label>
            <span className="tabular-nums text-sm text-brand">
              {formatPercent(values.confidence, 0)}
            </span>
          </div>
          <input
            id="confidence"
            type="range"
            min="0.5"
            max={confidenceMax}
            step="0.01"
            value={values.confidence}
            onChange={(event) => update({ confidence: Number(event.target.value) })}
            className="w-full accent-[var(--color-brand)]"
          />
          <p className="mt-1.5 text-xs text-muted">
            이 값 미만이면 엔지니어 검토로 넘깁니다. 권장 75~85%. 높일수록 품질은
            올라가지만 검토 부담이 늘어납니다.
          </p>
          {profile && (
            <p className="mt-1.5 text-xs text-muted tabular-nums">
              테스트 셋 {profile.n.toLocaleString()}건 기준 검토 대기 약{' '}
              <span className={reviewRate >= REVIEW_WARN ? 'font-semibold text-warn' : 'text-ink'}>
                {formatPercent(reviewRate, 1)}
              </span>
              {' '}· 이 모델의 확신도는 최대 {formatPercent(profile.confidence_max, 1)}라 슬라이더도
              거기까지만 올라갑니다.
            </p>
          )}
          {reviewRate !== null && reviewRate >= REVIEW_WARN && (
            <div
              className={`mt-2 rounded-lg border px-3 py-2 text-xs ${
                reviewRate >= REVIEW_DANGER
                  ? 'border-danger/40 bg-danger/10 text-danger'
                  : 'border-warn/40 bg-warn/10 text-warn'
              }`}
            >
              이 값이면 웨이퍼의 {formatPercent(reviewRate, 0)}가 검토 대기로 갑니다
              {reviewRate >= REVIEW_DANGER ? ' — 대기열이 감당할 수 없습니다.' : '.'} 이 모델의
              확신도는 대부분 90~92% 사이에 몰려 있어, 그 구간에서는 1%p 차이로 검토량이 몇 배씩
              달라집니다.
            </div>
          )}
        </div>

        <div className="border-t border-line pt-5">
          <div className="mb-2 flex items-baseline justify-between">
            <label htmlFor="high-density" className="text-sm font-medium">
              Near-full 강제 판정 밀도
            </label>
            <span className="tabular-nums text-sm text-brand">
              {values.high_density === null ? '사용 안 함' : formatPercent(values.high_density, 0)}
            </span>
          </div>
          <input
            id="high-density"
            type="range"
            min="0.5"
            max="0.99"
            step="0.01"
            value={values.high_density ?? 0.8}
            disabled={values.high_density === null}
            onChange={(event) => update({ high_density: Number(event.target.value) })}
            className="w-full accent-[var(--color-brand)] disabled:opacity-40"
          />
          <label className="mt-2 flex items-center gap-2 text-xs text-muted">
            <input
              type="checkbox"
              checked={values.high_density !== null}
              onChange={(event) => update({ high_density: event.target.checked ? 0.8 : null })}
            />
            사용 (결함 밀도가 이 값을 넘으면 AI 와 무관하게 Near-full 로 확정)
          </label>
        </div>

        <div className="border-t border-line pt-5">
          <div className="mb-2 flex items-baseline justify-between">
            <label htmlFor="low-density" className="text-sm font-medium">
              정상 강제 판정 밀도
            </label>
            <span className="tabular-nums text-sm text-muted">
              {values.low_density === null ? '사용 안 함' : formatPercent(values.low_density, 0)}
            </span>
          </div>
          <input
            id="low-density"
            type="range"
            min="0.005"
            max="0.2"
            step="0.005"
            value={values.low_density ?? 0.05}
            disabled={values.low_density === null}
            onChange={(event) => update({ low_density: Number(event.target.value) })}
            className="w-full accent-[var(--color-brand)] disabled:opacity-40"
          />
          <label className="mt-2 flex items-center gap-2 text-xs text-muted">
            <input
              type="checkbox"
              checked={values.low_density !== null}
              onChange={(event) => update({ low_density: event.target.checked ? 0.05 : null })}
            />
            사용
          </label>
          <div className="mt-2 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
            학습에 쓰지 않은 테스트 셋 17,504건에서 이 규칙을 켜면, 사람이 보지 않고
            정상으로 나가는 결함이 19건에서 140건으로 늘었습니다. 얇은 Scratch 와 작은 Loc 은
            결함 다이가 5% 미만이어도 명백한 결함인데, 픽셀을 세는 규칙은 패턴을 못 봅니다.
            켜지 않는 것을 권장합니다.
          </div>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={save}
          disabled={busy}
          className="rounded-lg bg-brand px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {busy ? '저장 중…' : '저장하기'}
        </button>
        {saved && <span className="text-sm text-pass">저장했습니다</span>}
        {meta?.updated_at && (
          <span className="text-xs text-muted">
            마지막 변경 {formatTime(meta.updated_at)} · {meta.updated_by}
          </span>
        )}
      </div>
    </div>
  )
}
