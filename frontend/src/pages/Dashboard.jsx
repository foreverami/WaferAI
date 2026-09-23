/**
 * 메인 대시보드 — UIUX 문서 화면 1.
 * 상단 KPI 요약 → 하단 웨이퍼 목록. 요약을 먼저 보고 상세로 내려가는 흐름.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, formatPercent, formatTime } from '../api'
import WaferDetail from '../components/WaferDetail'
import WaferMap from '../components/WaferMap'
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
  const [uploading, setUploading] = useState(false)
  const [uploadNote, setUploadNote] = useState(null)
  const fileInput = useRef(null)
  const navigate = useNavigate()

  const load = useCallback(() => {
    setError(null)
    api
      .records({ limit: 50 })
      .then(setRecords)
      .catch((caught) => setError(caught.detail || '목록을 불러오지 못했습니다'))
  }, [])

  useEffect(load, [load])

  const handleUpload = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setUploading(true)
    setUploadNote(null)
    setError(null)
    try {
      const created = await api.predict(file)
      setUploadNote(`${file.name} → ${created.final_class}`)
      load()
      setSelected(created.wafer_id)
    } catch (caught) {
      setError(caught.detail || '업로드에 실패했습니다')
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
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
          {uploadNote && <span className="text-sm text-pass">{uploadNote}</span>}
          <input
            ref={fileInput}
            type="file"
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
            {uploading ? '분석 중…' : '웨이퍼 업로드'}
          </label>
        </div>
      </div>

      <p className="text-xs text-muted">
        웨이퍼 맵 데이터(.npy / .csv / .json) 또는 학습과 같은 색으로 렌더링한 이미지(.png /
        .jpg)를 올릴 수 있습니다. 이미지는 224×224 를 권장합니다.
      </p>

      <ErrorNote onRetry={load}>{error}</ErrorNote>

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
          waferId={selected}
          onClose={() => setSelected(null)}
          onReviewed={load}
        />
      )}
    </div>
  )
}
