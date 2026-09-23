import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth'
import { ErrorNote } from '../components/ui'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [employeeId, setEmployeeId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(employeeId.trim(), password)
      // 로그인 전에 가려던 곳이 있으면 그리로, 없으면 메인으로.
      navigate(location.state?.from || '/', { replace: true })
    } catch (caught) {
      setError(caught.detail || '로그인에 실패했습니다')
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">
            WaferAI <span className="text-brand">·</span> Fab AI Inspector
          </h1>
          <p className="mt-2 text-sm text-muted">사번과 비밀번호로 로그인하세요</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="employee-id" className="mb-1.5 block text-sm text-muted">
              사번
            </label>
            <input
              id="employee-id"
              value={employeeId}
              onChange={(event) => setEmployeeId(event.target.value)}
              autoComplete="username"
              required
              className="w-full rounded-lg border border-line bg-panel px-3 py-2.5 text-sm outline-none focus:border-brand"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1.5 block text-sm text-muted">
              비밀번호
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
              className="w-full rounded-lg border border-line bg-panel px-3 py-2.5 text-sm outline-none focus:border-brand"
            />
          </div>

          <ErrorNote>{error}</ErrorNote>

          <button
            type="submit"
            disabled={busy || !employeeId || !password}
            className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {busy ? '확인 중…' : '로그인'}
          </button>
        </form>
      </div>
    </div>
  )
}
