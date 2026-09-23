/**
 * 리뷰 대기열 — UIUX 문서 화면 3.
 * 확신도 미달 건을 모아 처리하는 작업 큐. 클래스별 필터로 같은 유형을 묶어
 * 처리하면 맥락 전환 비용이 줄어든다.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'

import { api, formatPercent, formatTime } from '../api'
import WaferDetail from '../components/WaferDetail'
import { DecisionBadge, EmptyNote, ErrorNote, Spinner } from '../components/ui'

export default function ReviewQueue() {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [filter, setFilter] = useState('')

  const load = useCallback(() => {
    setError(null)
    api
      .records({ reviewOnly: true, limit: 200 })
      .then(setRows)
      .catch((caught) => setError(caught.detail || '대기열을 불러오지 못했습니다'))
  }, [])

  useEffect(load, [load])

  const classes = useMemo(
    () => [...new Set((rows || []).map((row) => row.final_class))].sort(),
    [rows],
  )
  const visible = filter ? rows?.filter((row) => row.final_class === filter) : rows

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold">리뷰 대기열</h2>
        <p className="text-sm text-muted">
          AI 확신도가 임계값에 못 미쳐 엔지니어 확인이 필요한 건입니다.
        </p>
      </div>

      <ErrorNote onRetry={load}>{error}</ErrorNote>

      {classes.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setFilter('')}
            className={`rounded-full border px-3 py-1 text-sm transition-colors ${
              filter === '' ? 'border-brand bg-brand/15 text-brand' : 'border-line text-muted'
            }`}
          >
            전체 {rows?.length ?? 0}
          </button>
          {classes.map((name) => {
            const count = rows.filter((row) => row.final_class === name).length
            return (
              <button
                key={name}
                onClick={() => setFilter(name)}
                className={`rounded-full border px-3 py-1 text-sm transition-colors ${
                  filter === name
                    ? 'border-brand bg-brand/15 text-brand'
                    : 'border-line text-muted hover:text-ink'
                }`}
              >
                {name} {count}
              </button>
            )
          })}
        </div>
      )}

      {!rows && !error && <Spinner />}

      {rows?.length === 0 && <EmptyNote>검토 대기 중인 웨이퍼가 없습니다.</EmptyNote>}

      {visible?.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-line">
          <table className="w-full text-sm">
            <thead className="bg-panel text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-3 font-medium">파일</th>
                <th className="px-4 py-3 font-medium">AI 예측</th>
                <th className="px-4 py-3 font-medium">확신도</th>
                <th className="px-4 py-3 font-medium">상태</th>
                <th className="px-4 py-3 font-medium">등록</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={row.wafer_id} className="border-t border-line">
                  <td className="max-w-50 truncate px-4 py-3">{row.filename || '이름 없음'}</td>
                  <td className="px-4 py-3 font-medium">{row.final_class}</td>
                  <td className="px-4 py-3">
                    {/* 숫자만 있으면 스캔이 느려서 열 안에서 길이로도 읽히게 한다 */}
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
                        <div
                          className="h-full rounded-full bg-warn"
                          style={{ width: `${row.confidence * 100}%` }}
                        />
                      </div>
                      <span className="tabular-nums text-muted">
                        {formatPercent(row.confidence)}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <DecisionBadge path={row.decision_path} />
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">{formatTime(row.processed_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setSelected(row.wafer_id)}
                      className="rounded-lg border border-line px-3 py-1.5 text-xs transition-colors hover:border-brand"
                    >
                      상세 보기
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <WaferDetail
          waferId={selected}
          onClose={() => setSelected(null)}
          // 검토가 끝나면 대기열에서 빠지므로 목록을 다시 읽는다.
          onReviewed={load}
        />
      )}
    </div>
  )
}
