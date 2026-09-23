/**
 * 설정 — UIUX 문서 화면 6·7의 임계값 슬라이더.
 * 수석 엔지니어 이상만 들어온다(서버에서도 막는다).
 */
import { useEffect, useState } from 'react'

import { api, formatPercent, formatTime } from '../api'
import { ErrorNote, Spinner } from '../components/ui'

export default function Settings() {
  const [values, setValues] = useState(null)
  const [meta, setMeta] = useState(null)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .thresholds()
      .then(({ updated_at, updated_by, ...rest }) => {
        setValues(rest)
        setMeta({ updated_at, updated_by })
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
      const { updated_at, updated_by, ...rest } = await api.saveThresholds(values)
      setValues(rest)
      setMeta({ updated_at, updated_by })
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
            max="0.99"
            step="0.01"
            value={values.confidence}
            onChange={(event) => update({ confidence: Number(event.target.value) })}
            className="w-full accent-[var(--color-brand)]"
          />
          <p className="mt-1.5 text-xs text-muted">
            이 값 미만이면 엔지니어 검토로 넘깁니다. 권장 75~85%. 높일수록 품질은
            올라가지만 검토 부담이 늘어납니다.
          </p>
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
            검증 데이터 10,208건 측정 결과 이 규칙은 정확도를 떨어뜨렸습니다. 걸린 1,087건
            중 291건이 실제로는 결함이었습니다(전체 정확도 96.45% → 93.78%). 켜지 않는
            것을 권장합니다.
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
