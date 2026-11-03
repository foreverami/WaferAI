/**
 * 가입 신청 — 로그인 없이 들어오는 유일한 화면.
 *
 * 신청하면 계정은 '승인 대기' 로 만들어지고, 관리자가 계정 탭에서 승인해야 로그인할 수 있다.
 * 공장 품질 시스템이라 주소만 알면 누구나 들어오는 구조를 피한다. 권한은 고를 수 없고
 * 엔지니어로 시작한다(승격은 관리자만).
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api'
import { ErrorNote } from '../components/ui'

const MIN_PASSWORD = 8
const INPUT =
  'w-full rounded-lg border border-line bg-panel px-3 py-2.5 text-sm outline-none focus:border-brand'

function Field({ id, label, hint, children }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm text-muted">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  )
}

export default function Signup() {
  const [form, setForm] = useState({
    employee_id: '', name: '', email: '', department: '', password: '', confirm: '',
  })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)

  const update = (patch) => {
    setForm((current) => ({ ...current, ...patch }))
    setError(null)
  }

  const mismatch = form.confirm.length > 0 && form.password !== form.confirm
  const tooShort = form.password.length > 0 && form.password.length < MIN_PASSWORD
  const ready =
    form.employee_id.trim() && form.name.trim() && form.email.trim() &&
    form.password.length >= MIN_PASSWORD && form.password === form.confirm && !busy

  const handleSubmit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const user = await api.register({
        employee_id: form.employee_id.trim(),
        name: form.name.trim(),
        email: form.email.trim(),
        department: form.department.trim() || null,
        password: form.password,
      })
      setDone(user)
    } catch (caught) {
      setError(caught.detail || '가입 신청에 실패했습니다')
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <div className="flex min-h-full items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm space-y-4 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">신청을 받았습니다</h1>
          <p className="text-sm text-muted">
            사번 <span className="font-mono text-ink">{done.employee_id}</span> 으로 신청됐습니다.
            관리자가 승인하면 로그인할 수 있습니다. 승인 여부는 관리자에게 확인하세요.
          </p>
          <Link
            to="/login"
            className="inline-block rounded-lg bg-brand px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            로그인 화면으로
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-full items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">
            WaferAI <span className="text-brand">·</span> 가입 신청
          </h1>
          <p className="mt-2 text-sm text-muted">
            신청 후 관리자가 승인하면 엔지니어 권한으로 로그인할 수 있습니다
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Field id="employee-id" label="사번" hint="나중에 바꿀 수 없습니다">
            <input id="employee-id" value={form.employee_id} maxLength={20} required
                   autoComplete="username" className={INPUT}
                   onChange={(e) => update({ employee_id: e.target.value })} />
          </Field>
          <Field id="name" label="이름">
            <input id="name" value={form.name} maxLength={50} required autoComplete="name"
                   className={INPUT} onChange={(e) => update({ name: e.target.value })} />
          </Field>
          <Field id="email" label="이메일">
            <input id="email" type="email" value={form.email} required autoComplete="email"
                   className={INPUT} onChange={(e) => update({ email: e.target.value })} />
          </Field>
          <Field id="department" label="부서 (선택)">
            <input id="department" value={form.department} maxLength={50}
                   autoComplete="organization" className={INPUT}
                   onChange={(e) => update({ department: e.target.value })} />
          </Field>
          <Field id="password" label="비밀번호"
                 hint={tooShort ? `${MIN_PASSWORD}자 이상이어야 합니다` : `${MIN_PASSWORD}자 이상. 한글을 포함해 어떤 문자든 쓸 수 있습니다`}>
            <input id="password" type="password" value={form.password} minLength={MIN_PASSWORD}
                   required autoComplete="new-password" className={INPUT}
                   onChange={(e) => update({ password: e.target.value })} />
          </Field>
          <Field id="confirm" label="비밀번호 확인" hint={mismatch ? '비밀번호와 다릅니다' : undefined}>
            <input id="confirm" type="password" value={form.confirm} required
                   autoComplete="new-password" className={INPUT}
                   onChange={(e) => update({ confirm: e.target.value })} />
          </Field>

          <ErrorNote>{error}</ErrorNote>

          <button
            type="submit"
            disabled={!ready}
            className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {busy ? '신청 중…' : '가입 신청'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-muted">
          이미 계정이 있으신가요?{' '}
          <Link to="/login" className="text-brand underline underline-offset-2">
            로그인
          </Link>
        </p>
      </div>
    </div>
  )
}
