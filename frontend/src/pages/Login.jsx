import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

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
      const me = await login(employeeId.trim(), password)
      // 임시 비밀번호면 먼저 바꾸게 한다. 아니면 로그인 전에 가려던 곳으로, 없으면 메인으로.
      navigate(me.must_change_password ? '/account' : location.state?.from || '/', { replace: true })
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

        <p className="mt-6 text-center text-sm text-muted">
          계정이 없으신가요?{' '}
          <Link to="/signup" className="text-brand underline underline-offset-2">
            가입 신청
          </Link>
        </p>
        <p className="mt-2 text-center text-xs text-muted">
          비밀번호를 잊으셨나요? 관리자에게 초기화를 요청하세요. 임시 비밀번호로 로그인하면 바로
          바꾸게 됩니다. 5회 연속 틀리면 잠시 잠깁니다.
        </p>
      </div>
    </div>
  )
}
