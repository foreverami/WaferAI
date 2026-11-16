/**
 * 메인 대시보드 — UIUX 문서 화면 1.
 * 상단 KPI 요약 → 하단 웨이퍼 목록. 요약을 먼저 보고 상세로 내려가는 흐름.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, formatPercent, formatTime } from '../api'
import WaferDetail from '../components/WaferDetail'
import {
  DecisionBadge,
  EmptyNote,
  ErrorNote,
  KpiCard,
  ReviewedBadge,
  Spinner,
} from '../components/ui'

export default function Dashboard() {
  const [records, setRecords] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  // 여러 장 올리기 — { done, total } 진행 상황과 파일별 결과
  const [progress, setProgress] = useState(null)
  const [batch, setBatch] = useState(null)
  const fileInput = useRef(null)
  const navigate = useNavigate()
  const uploading = progress !== null

  // 효과 안에서 상태를 동기적으로 바꾸지 않는다. 오류 초기화도 응답이 온 뒤에 한다.
  const load = useCallback(() => {
    api
      .records({ limit: 50 })
      .then((list) => {
        setError(null)
        setRecords(list)
      })
      .catch((caught) => setError(caught.detail || '목록을 불러오지 못했습니다'))
  }, [])

  useEffect(load, [load])

  /**
   * 한 장이든 여러 장이든 같은 길로 올린다. 서버의 추론은 한 번에 한 장씩 돌므로(추론 잠금)
   * 동시에 쏘아도 빨라지지 않는다 — 차례로 보내고 진행률을 보여 준다. 한 장이 실패해도 나머지는
   * 계속 올리고, 실패 이유를 파일 옆에 적는다.
   */
  const handleUpload = async (event) => {
    const files = Array.from(event.target.files || [])
    if (!files.length) return
    setError(null)
    setBatch(null)
    const results = []
    for (const [index, file] of files.entries()) {
      setProgress({ done: index, total: files.length })
      try {
        const created = await api.predict(file)
        results.push({ name: file.name, ok: true, wafer: created })
      } catch (caught) {
        results.push({ name: file.name, ok: false, detail: caught.detail || '업로드에 실패했습니다' })
      }
    }
    setProgress(null)
    if (fileInput.current) fileInput.current.value = ''
    load()
    if (files.length === 1 && results[0].ok) {
      setSelected(results[0].wafer.wafer_id)
    } else if (files.length === 1) {
      setError(results[0].detail)
    } else {
      setBatch(results)
    }
  }

  const total = records?.length ?? 0
  const autoPass = records?.filter((row) => row.decision_path === 'AUTO_PASS').length ?? 0
  const ruleBase = records?.filter((row) => row.decision_path.startsWith('RULE_BASE')).length ?? 0
  const pending = records?.filter((row) => row.requires_human_review).length ?? 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">대시보드</h2>
          <p className="text-sm text-muted">최근 처리한 웨이퍼 {total}건</p>
        </div>

        <div className="flex items-center gap-3">
          <a
            href={api.exportUrl()}
            download
            className="rounded-lg border border-line px-3 py-2 text-sm text-muted transition-colors hover:border-brand hover:text-ink"
          >
            기록 CSV
          </a>
          <input
            ref={fileInput}
            type="file"
            multiple
            accept=".npy,.csv,.json,.png,.jpg,.jpeg"
            onChange={handleUpload}
            className="hidden"
            id="wafer-upload"
          />
          <label
            htmlFor="wafer-upload"
            className={`cursor-pointer rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 ${
              uploading ? 'pointer-events-none opacity-50' : ''
            }`}
          >
            {uploading ? `분석 중… ${progress.done + 1}/${progress.total}` : '웨이퍼 업로드'}
          </label>
        </div>
      </div>

      <p className="text-xs text-muted">
        웨이퍼 맵 데이터(.npy / .csv / .json) 또는 웨이퍼 맵을 3색으로 그린 이미지(.png / .jpg)를
        올릴 수 있습니다. 여러 파일을 한 번에 고를 수 있습니다. 학습 색과 viridis · 회색조는 바로 읽고,
        처음 보는 색은 추정해 읽은 뒤 사람 검토로 보냅니다. 이미지는 224×224 를 권장합니다.
      </p>

      <ErrorNote onRetry={load}>{error}</ErrorNote>

      {batch && (
        <div className="rounded-xl border border-line bg-panel p-4 text-sm">
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="font-medium">
              {batch.length}개 중 {batch.filter((item) => item.ok).length}개 분석 ·{' '}
              검토 필요 {batch.filter((item) => item.ok && item.wafer.requires_human_review).length}개
              {batch.some((item) => !item.ok) && (
                <span className="text-danger"> · 실패 {batch.filter((item) => !item.ok).length}개</span>
              )}
            </p>
            <button onClick={() => setBatch(null)} className="text-xs text-muted underline underline-offset-2">
              닫기
            </button>
          </div>
          <ul className="max-h-56 space-y-1 overflow-y-auto text-xs">
            {batch.map((item, index) => (
              <li key={`${item.name}-${index}`} className="flex items-center justify-between gap-3">
                <span className="truncate">{item.name}</span>
                {item.ok ? (
                  <button
                    onClick={() => setSelected(item.wafer.wafer_id)}
                    className="flex shrink-0 items-center gap-2 hover:underline"
                  >
                    <span className="font-medium">{item.wafer.final_class}</span>
                    <DecisionBadge path={item.wafer.decision_path} />
                  </button>
                ) : (
                  <span className="shrink-0 text-danger">{item.detail}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="총 처리량" value={total} hint="최근 50건 기준" />
        <KpiCard
          label="AI 자동 통과"
          value={autoPass}
          tone="pass"
          hint={total ? formatPercent(autoPass / total, 0) : '-'}
        />
        <KpiCard
          label="규칙 확정"
          value={ruleBase}
          tone="brand"
          hint={total ? formatPercent(ruleBase / total, 0) : '-'}
        />
        <KpiCard
          label="검토 필요"
          value={pending}
          tone="danger"
          hint="클릭하면 대기열로"
          onClick={() => navigate('/review')}
        />
      </div>

      {!records && !error && <Spinner />}

      {records?.length === 0 && (
        <EmptyNote>아직 분석한 웨이퍼가 없습니다. 위에서 파일을 올려보세요.</EmptyNote>
      )}

      {records?.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {records.map((row) => (
            <button
              key={row.wafer_id}
              onClick={() => setSelected(row.wafer_id)}
              className="rounded-xl border border-line bg-panel p-4 text-left transition-colors hover:border-brand/60"
            >
              <div className="mb-3 flex items-center justify-between gap-2">
                <DecisionBadge path={row.decision_path} />
                {row.latest_review ? (
                  <ReviewedBadge />
                ) : (
                  <span className="text-xs text-muted">
                    {row.input_type === 'image' ? '이미지' : '데이터'}
                  </span>
                )}
              </div>

              <img
                src={api.thumbnailUrl(row.wafer_id)}
                alt=""
                loading="lazy"
                className="wafer-image mb-3 w-full rounded-lg bg-black"
              />

              <p className="truncate text-sm font-medium">{row.filename || '이름 없음'}</p>
              <p className="mt-1 text-sm">
                <span className="text-muted">예측 </span>
                <span className="font-medium">{row.final_class}</span>
                <span className="ml-2 tabular-nums text-muted">
                  {formatPercent(row.confidence)}
                </span>
              </p>
              <p className="mt-1 text-xs text-muted">{formatTime(row.processed_at)}</p>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <WaferDetail
          key={selected}
          waferId={selected}
          onClose={() => setSelected(null)}
          onReviewed={load}
        />
      )}
    </div>
  )
}
