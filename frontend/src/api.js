/**
 * 백엔드 호출 래퍼.
 *
 * 토큰을 자바스크립트가 다루지 않는다. 인증은 httpOnly 쿠키로만 오가므로
 * `credentials: 'include'` 만 붙이면 되고, 저장할 것도 지울 것도 없다.
 */

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `요청이 실패했습니다 (${status})`)
    this.status = status
    this.detail = detail
  }
}

async function request(path, { method = 'GET', body, form, signal } = {}) {
  const init = { method, credentials: 'include', signal, headers: {} }

  if (form) {
    init.body = form // multipart 경계는 브라우저가 붙인다. Content-Type 을 직접 넣으면 깨진다.
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  const response = await fetch(path, init)
  if (response.status === 204) return null

  if (!response.ok) {
    let detail
    try {
      const payload = await response.json()
      // FastAPI 검증 오류는 detail 이 배열로 온다.
      detail = Array.isArray(payload.detail)
        ? payload.detail.map((item) => item.msg).join(', ')
        : payload.detail
    } catch {
      detail = null
    }
    throw new ApiError(response.status, detail)
  }

  const type = response.headers.get('content-type') || ''
  return type.includes('application/json') ? response.json() : response.blob()
}

export const api = {
  login: (employeeId, password) =>
    request('/api/auth/login', { method: 'POST', body: { employee_id: employeeId, password } }),
  logout: () => request('/api/auth/logout', { method: 'POST' }),
  me: () => request('/api/auth/me'),
  changePassword: (currentPassword, newPassword) =>
    request('/api/auth/password', {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword },
    }),

  status: () => request('/api/status'),

  records: ({ reviewOnly = false, limit = 50, offset = 0 } = {}) =>
    request(`/api/records?review_only=${reviewOnly}&limit=${limit}&offset=${offset}`),
  record: (id) => request(`/api/records/${id}`),

  predict: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/api/predict', { method: 'POST', form })
  },

  approve: (id, rank = 1, memo = '') =>
    request(`/api/records/${id}/approve`, { method: 'POST', body: { rank, memo } }),
  review: (id, label, memo = '') =>
    request(`/api/records/${id}/review`, { method: 'POST', body: { label, memo } }),

  // 이미지는 <img src> 로 직접 부른다. 쿠키는 같은 출처라 자동으로 실린다.
  // 목록에는 반드시 thumbnailUrl 을 쓴다. heatmapUrl 은 역전파를 돌리므로
  // 카드마다 부르면 지연 생성 설계가 무너진다.
  thumbnailUrl: (id) => `/api/records/${id}/thumbnail`,
  heatmapUrl: (id, className) =>
    `/api/records/${id}/heatmap${className ? `?class_name=${encodeURIComponent(className)}` : ''}`,

  thresholds: () => request('/api/settings/thresholds'),
  saveThresholds: (values) =>
    request('/api/settings/thresholds', { method: 'PUT', body: values }),
}

/** 확률 딕셔너리를 내림차순 배열로. */
export function ranked(probabilities) {
  return Object.entries(probabilities || {}).sort((a, b) => b[1] - a[1])
}

export function formatPercent(value, digits = 1) {
  return `${(value * 100).toFixed(digits)}%`
}

export function formatTime(isoString) {
  if (!isoString) return '-'
  const date = new Date(isoString)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('ko-KR')
}
