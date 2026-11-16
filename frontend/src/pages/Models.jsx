/**
 * AI 모델 관리 — UIUX 문서 화면 5.
 *
 * 운영 중인 모델, 재학습 진행 상황, 재학습 작업 이력을 보여준다.
 * 학습은 서버에서 돌리지 않는다(CPU 서버에서는 며칠이 걸리고 추론이 멈춘다).
 * 관리자가 학습 데이터를 내려받아 GPU 에서 학습하고, 새 모델을 올려 서버를 재시작하면
 * 작업이 자동으로 완료된다.
 */
import { useCallback, useEffect, useState } from 'react'

import { api, formatPercent, formatTime } from '../api'
import { useAuth } from '../authContext'
import TrendChart from '../components/TrendChart'
import { EmptyNote, ErrorNote, Spinner } from '../components/ui'

const STATUS = {
  PENDING: { label: '대기', className: 'border-warn/40 bg-warn/15 text-warn' },
  RUNNING: { label: '학습 중', className: 'border-brand/40 bg-brand/15 text-brand' },
  COMPLETED: { label: '완료', className: 'border-pass/40 bg-pass/15 text-pass' },
  FAILED: { label: '실패', className: 'border-danger/40 bg-danger/15 text-danger' },
}

function StatusBadge({ status }) {
  const style = STATUS[status] || { label: status, className: 'border-line text-muted' }
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${style.className}`}>
      {style.label}
    </span>
  )
}

function triggerLabel(value) {
  return value === 'AUTO_RETRAIN_500' ? '자동 (검토 누적)' : `관리자 ${value}`
}

function TestMetrics({ model }) {
  if (!model.has_clean_test) {
    return (
      <div className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
        1학기 모델 — 독립 테스트 셋 없이 학습해, 표시된 수치는 검증 정확도입니다. 결함 샘플을
        모두 학습·검증에 써서 오염되지 않은 테스트 정확도가 없습니다.
      </div>
    )
  }
  const { balanced, natural } = model.test_metrics
  return (
    <dl className="grid grid-cols-2 gap-3 text-sm">
      {[
        ['테스트 정확도 (균형)', balanced.accuracy],
        ['테스트 macro-F1 (균형)', balanced.macro_f1],
        ['테스트 정확도 (실제 분포)', natural.accuracy],
        ['테스트 macro-F1 (실제 분포)', natural.macro_f1],
      ].map(([label, value]) => (
        <div key={label} className="rounded-lg border border-line px-3 py-2">
          <dt className="text-xs text-muted">{label}</dt>
          <dd className="mt-0.5 text-lg font-semibold tabular-nums">{formatPercent(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

const EFFECT_ROWS = [
  ['검토 비율', 'review_rate', (v) => formatPercent(v, 2)],
  ['틀린 채 자동 통과', 'escaped', (v) => `${v}건`],
  ['결함을 정상으로', 'missed_defect', (v) => `${v}건`],
  ['자동 통과의 정확도', 'unattended_accuracy', (v) => formatPercent(v, 2)],
]

/** 확률 보정과 판정 기준 조정의 효과 — 학습에도 보정에도 쓰지 않은 테스트 셋에서 잰 값. */
function CalibrationCard({ calibration }) {
  if (!calibration?.test_effect) return null
  const { before, after } = calibration.test_effect
  return (
    <section className="space-y-3 rounded-xl border border-line bg-panel p-5">
      <div>
        <h3 className="font-semibold">확률 보정 · 판정 기준</h3>
        <p className="mt-0.5 text-xs text-muted">
          검증 분할로 맞추고 테스트 셋 {before.n.toLocaleString()}건으로 잰 값입니다. 온도 T ={' '}
          {calibration.temperature} · 확신도 보정 오차(ECE) {calibration.ece?.test_before} →{' '}
          {calibration.ece?.test_after}
        </p>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted">
          <tr>
            <th className="py-1.5 font-medium" />
            <th className="py-1.5 text-right font-medium">보정 전 (0.80)</th>
            <th className="py-1.5 text-right font-medium">지금</th>
          </tr>
        </thead>
        <tbody>
          {EFFECT_ROWS.map(([label, key, format]) => (
            <tr key={key} className="border-t border-line">
              <td className="py-1.5 text-muted">{label}</td>
              <td className="py-1.5 text-right tabular-nums">{format(before[key])}</td>
              <td className="py-1.5 text-right font-medium tabular-nums">{format(after[key])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-muted">
        검토가 조금 늘어나는 대신 사람 없이 틀린 채 나가는 웨이퍼가 줄어듭니다. 설정 화면에서 클래스별
        기준을 끄면 단일 임계값으로 돌아갑니다.
      </p>
    </section>
  )
}

/** 서버 상태 — 디스크와 백업. 따로 감시 도구가 없는 배포라 관리자가 화면에서 확인한다. */
function HealthCard({ health }) {
  if (!health) return null
  // 경과 시간은 서버가 잰다 (화면에서 현재 시각을 읽으면 그릴 때마다 값이 바뀐다)
  const backupStale = health.last_backup_age_hours == null || health.last_backup_age_hours > 36
  const diskLow = health.disk_free_gb < 5
  return (
    <section className="space-y-3 rounded-xl border border-line bg-panel p-5">
      <h3 className="font-semibold">서버 상태</h3>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div className={`rounded-lg border px-3 py-2 ${diskLow ? 'border-danger/40 bg-danger/10' : 'border-line'}`}>
          <dt className="text-xs text-muted">디스크 남은 공간</dt>
          <dd className="mt-0.5 font-semibold tabular-nums">
            {health.disk_free_gb} / {health.disk_total_gb} GB{diskLow ? ' · 부족' : ''}
          </dd>
        </div>
        <div className={`rounded-lg border px-3 py-2 ${backupStale ? 'border-warn/40 bg-warn/10' : 'border-line'}`}>
          <dt className="text-xs text-muted">마지막 DB 백업</dt>
          <dd className="mt-0.5 font-semibold">
            {health.last_backup_at
              ? `${formatTime(health.last_backup_at)} · ${health.last_backup_mb} MB`
              : '없음'}
            {backupStale ? ' · 확인 필요' : ''}
          </dd>
        </div>
      </dl>
      <p className="text-xs text-muted tabular-nums">
        보관 중인 백업 {health.backups}개 · 판정 기록 {health.database_rows.wafer_result.toLocaleString()}건 ·
        검토 {health.database_rows.review_result.toLocaleString()}건 · 감사 기록{' '}
        {health.database_rows.audit_events.toLocaleString()}건
      </p>
    </section>
  )
}

export default function Models() {
  const { can } = useAuth()
  const isAdmin = can('admin')
  const [models, setModels] = useState(null)
  const [overview, setOverview] = useState(null)
  const [jobs, setJobs] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [trend, setTrend] = useState(null)
  const [calibration, setCalibration] = useState(null)
  const [health, setHealth] = useState(null)

  // 효과 안에서 상태를 동기적으로 바꾸지 않는다. 오류 초기화도 응답이 온 뒤에 한다.
  const load = useCallback(() => {
    Promise.all([api.models(), api.retrainOverview(), api.retrainJobs(), api.trend(12), api.status()])
      .then(([modelList, state, jobList, trendData, status]) => {
        setError(null)
        setModels(modelList)
        setOverview(state)
        setJobs(jobList)
        setTrend(trendData.weeks)
        setCalibration(status.metadata?.calibration || null)
      })
      .catch((caught) => setError(caught.detail || '모델 정보를 불러오지 못했습니다'))
    if (isAdmin) {
      api.systemHealth().then(setHealth).catch(() => setHealth(null))
    }
  }, [isAdmin])

  useEffect(load, [load])

  const act = async (operation) => {
    setBusy(true)
    setError(null)
    try {
      await operation()
      load()
    } catch (caught) {
      setError(caught.detail || '처리에 실패했습니다')
    } finally {
      setBusy(false)
    }
  }

  const failActive = () => {
    const note = window.prompt('실패 사유를 적어주세요 (예: 승격 기준 미달 — balanced macro-F1 0.82)')
    if (note && note.trim()) act(() => api.failJob(overview.active_job.job_id, note.trim()))
  }

  if (!models || !overview || !jobs) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-semibold">AI 모델 관리</h2>
        <ErrorNote onRetry={load}>{error}</ErrorNote>
        {!error && <Spinner />}
      </div>
    )
  }

  const active = models.find((model) => model.is_active)
  const job = overview.active_job

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">AI 모델 관리</h2>
        <p className="text-sm text-muted">
          운영 중인 모델과 재학습 진행 상황입니다. 엔지니어 검토가 쌓이면 재학습 작업이 만들어집니다.
        </p>
      </div>

      <ErrorNote>{error}</ErrorNote>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 운영 중인 모델 */}
        <section className="space-y-4 rounded-xl border border-line bg-panel p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs text-muted">운영 중인 모델</p>
              <p className="mt-1 font-semibold">{active ? `${active.model_name} · ${active.version}` : '없음'}</p>
            </div>
            {active && (
              <span className="rounded-full border border-pass/40 bg-pass/15 px-2.5 py-0.5 text-xs text-pass">
                {active.backend}
              </span>
            )}
          </div>
          {active && (
            <>
              <dl className="space-y-1.5 text-xs text-muted">
                <div className="flex justify-between">
                  <dt>검증 정확도</dt>
                  <dd className="tabular-nums text-ink">
                    {active.val_accuracy != null ? `${active.val_accuracy.toFixed(2)}%` : '-'}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt>배포</dt>
                  <dd className="text-ink">{formatTime(active.deployed_at)}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt>가중치</dt>
                  <dd className="truncate font-mono text-ink">{active.file_sha256.slice(0, 12)}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt>학습 분할</dt>
                  <dd className="font-mono text-ink">{active.split_id || '없음'}</dd>
                </div>
              </dl>
              <TestMetrics model={active} />
            </>
          )}
        </section>

        {/* 재학습 진행 */}
        <section className="space-y-4 rounded-xl border border-line bg-panel p-5">
          <div>
            <p className="text-xs text-muted">재학습까지</p>
            <p className="mt-1 text-sm">
              직전 재학습 이후 검토된 웨이퍼{' '}
              <strong className="tabular-nums">{overview.new_reviews.toLocaleString()}</strong>
              <span className="text-muted"> / {overview.threshold.toLocaleString()}</span>
            </p>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-line">
              <div className="h-full rounded-full bg-brand" style={{ width: `${overview.ratio * 100}%` }} />
            </div>
            <p className="mt-1.5 text-xs text-muted">
              {overview.threshold.toLocaleString()}건이 쌓이면 재학습 작업이 자동으로 만들어집니다.
            </p>
          </div>

          {job ? (
            <div className="space-y-3 border-t border-line pt-4">
              <div className="flex items-center gap-2">
                <StatusBadge status={job.status} />
                <span className="text-xs text-muted">
                  {triggerLabel(job.triggered_by)} · 새 검토 {job.new_reviews.toLocaleString()}건 ·{' '}
                  {formatTime(job.created_at)}
                </span>
              </div>
              <ol className="list-decimal space-y-1 pl-5 text-xs text-muted">
                <li className={job.status === 'PENDING' ? 'text-ink' : ''}>학습 데이터를 내려받습니다 (→ 학습 중)</li>
                <li className={job.status === 'RUNNING' ? 'text-ink' : ''}>
                  GPU 에서 학습합니다 — <code>python3 -m scripts.train --reviews 파일</code>
                </li>
                <li>
                  고정 테스트 셋으로 판정해 교체합니다 — <code>python3 -m scripts.promote_model --apply</code>
                </li>
                <li>models/ 를 서버로 옮기고 api 를 재시작하면 이 작업이 완료됩니다</li>
              </ol>
              {isAdmin && (
                <div className="flex flex-wrap gap-2">
                  <a
                    href={api.datasetUrl(job.job_id)}
                    download
                    onClick={() => setTimeout(load, 1500)}
                    className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90"
                  >
                    학습 데이터 내려받기
                  </a>
                  <button
                    onClick={failActive}
                    disabled={busy}
                    className="rounded-lg border border-line px-4 py-2 text-sm text-muted hover:border-danger/50 hover:text-danger disabled:opacity-40"
                  >
                    실패로 표시
                  </button>
                </div>
              )}
            </div>
          ) : (
            isAdmin && (
              <div className="border-t border-line pt-4">
                <button
                  onClick={() => act(api.requestRetrain)}
                  disabled={busy || overview.new_reviews === 0}
                  className="rounded-lg border border-line px-4 py-2 text-sm transition-colors hover:border-brand disabled:opacity-40"
                >
                  지금 재학습 요청
                </button>
                <p className="mt-1.5 text-xs text-muted">
                  기준에 못 미쳐도 요청할 수 있습니다. 새로 검토된 웨이퍼가 있어야 합니다.
                </p>
              </div>
            )
          )}
        </section>
      </div>

      {/* 성능 추이 */}
      <section className="space-y-3 rounded-xl border border-line bg-panel p-5">
        <div>
          <h3 className="font-semibold">성능 추이</h3>
          <p className="mt-0.5 text-xs text-muted">
            최근 12주 동안 주마다 올라온 웨이퍼의 처리 경로와, 사람이 검토한 건 중 AI 판정과 같았던 비율입니다.
          </p>
        </div>
        {trend && trend.length > 0 ? (
          <TrendChart weeks={trend} />
        ) : (
          <EmptyNote>최근 12주 동안 처리한 웨이퍼가 없습니다.</EmptyNote>
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <CalibrationCard calibration={calibration} />
        {isAdmin && <HealthCard health={health} />}
      </div>

      {/* 재학습 작업 이력 */}
      <section className="space-y-3">
        <h3 className="font-semibold">재학습 작업</h3>
        {jobs.length === 0 ? (
          <EmptyNote>아직 재학습 작업이 없습니다.</EmptyNote>
        ) : (
          <div className="overflow-hidden rounded-xl border border-line">
            <table className="w-full text-sm">
              <thead className="bg-panel text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-3 font-medium">생성</th>
                  <th className="px-4 py-3 font-medium">상태</th>
                  <th className="px-4 py-3 font-medium">요청</th>
                  <th className="px-4 py-3 font-medium">새 검토</th>
                  <th className="px-4 py-3 font-medium">모델</th>
                  <th className="px-4 py-3 font-medium">비고</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((item) => (
                  <tr key={item.job_id} className="border-t border-line">
                    <td className="px-4 py-3 text-xs text-muted">{formatTime(item.created_at)}</td>
                    <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
                    <td className="px-4 py-3 text-xs">{triggerLabel(item.triggered_by)}</td>
                    <td className="px-4 py-3 tabular-nums">{item.new_reviews.toLocaleString()}</td>
                    <td className="px-4 py-3 text-xs text-muted">
                      {item.base_model_id ?? '-'} → {item.result_model_id ?? '…'}
                    </td>
                    <td className="max-w-60 truncate px-4 py-3 text-xs text-muted">{item.note || ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* 모델 이력 */}
      <section className="space-y-3">
        <h3 className="font-semibold">배포 이력</h3>
        <div className="overflow-hidden rounded-xl border border-line">
          <table className="w-full text-sm">
            <thead className="bg-panel text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-3 font-medium">#</th>
                <th className="px-4 py-3 font-medium">모델</th>
                <th className="px-4 py-3 font-medium">검증 정확도</th>
                <th className="px-4 py-3 font-medium">테스트 macro-F1 (실제 분포)</th>
                <th className="px-4 py-3 font-medium">배포</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {models.map((model) => (
                <tr key={model.model_id} className="border-t border-line">
                  <td className="px-4 py-3 tabular-nums text-muted">{model.model_id}</td>
                  <td className="px-4 py-3">
                    {model.version}
                    <span className="ml-2 font-mono text-xs text-muted">{model.file_sha256.slice(0, 8)}</span>
                  </td>
                  <td className="px-4 py-3 tabular-nums">
                    {model.val_accuracy != null ? `${model.val_accuracy.toFixed(2)}%` : '-'}
                  </td>
                  <td className="px-4 py-3 tabular-nums">
                    {model.has_clean_test ? formatPercent(model.test_metrics.natural.macro_f1) : (
                      <span className="text-xs text-muted">테스트 셋 없음</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">{formatTime(model.deployed_at)}</td>
                  <td className="px-4 py-3 text-right">
                    {model.is_active && (
                      <span className="rounded-full border border-pass/40 bg-pass/15 px-2.5 py-0.5 text-xs text-pass">
                        운영 중
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
