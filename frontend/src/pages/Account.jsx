/**
 * 계정 — UIUX 문서 화면 8(계정 설정)과 사용자 · 권한 관리(관리자).
 *
 * 화면 8 의 핵심은 셋이다. 현재 권한을 배지로 명시해 권한 밖 행동을 미리 막고, 사번은
 * 고칠 수 없게 잠그고, 마지막 비밀번호 변경일을 보여 정기 변경을 유도한다.
 * 여기서 잠그고 감추는 것은 편의다. 실제 차단은 서버가 한다 — 사번은 기본키라 바꾸는
 * API 자체가 없고, 계정 관리 API 는 관리자만 통과시킨다.
 */
import { useEffect, useState } from 'react'

import { api, formatTime } from '../api'
import { ROLE_LABEL, useAuth } from '../auth'
import { EmptyNote, ErrorNote, Spinner } from '../components/ui'

const ROLE_STYLE = {
  engineer: 'bg-muted/15 text-muted border-muted/40',
  senior_engineer: 'bg-brand/15 text-brand border-brand/40',
  admin: 'bg-warn/15 text-warn border-warn/40',
}

/** 등급별 접근 범위. 상위 등급은 아래 등급의 것을 모두 포함한다. */
const SCOPES = [
  ['engineer', '웨이퍼 업로드 · 판정 결과 조회 · 검토(승인 · 수정 · 라벨링)'],
  ['senior_engineer', '판정 임계값 변경 · 모델 관리 조회'],
  ['admin', '계정 관리 · 재학습 요청과 학습 데이터 내려받기'],
]
const RANK = { engineer: 0, senior_engineer: 1, admin: 2 }

// 이 날짜가 지나면 비밀번호 변경을 권한다 (UIUX 화면 8 "정기 변경 주기 유도")
const PASSWORD_WARN_DAYS = 90
const MIN_PASSWORD = 8

const INPUT =
  'w-full rounded-lg border border-line bg-panel px-3 py-2.5 text-sm outline-none focus:border-brand disabled:cursor-not-allowed disabled:opacity-60'
const BUTTON =
  'rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40'

function RoleBadge({ role }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${
        ROLE_STYLE[role] || ROLE_STYLE.engineer
      }`}
    >
      {ROLE_LABEL[role] || role}
    </span>
  )
}

function daysSince(isoString) {
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return null
  return Math.floor((Date.now() - date.getTime()) / 86400000)
}

function Field({ label, children, hint }) {
  return (
    <div>
      <p className="mb-1.5 text-sm text-muted">{label}</p>
      {children}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  )
}

/** 내 계정 — 권한 배지, 잠긴 사번, 연락처, 비밀번호 변경일. */
function Profile({ user }) {
  const age = daysSince(user.password_changed_at)
  const stale = age !== null && age > PASSWORD_WARN_DAYS

  return (
    <section className="space-y-5 rounded-xl border border-line bg-panel p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-semibold">내 계정</h3>
          <p className="mt-0.5 text-xs text-muted">현재 권한</p>
        </div>
        <RoleBadge role={user.role} />
      </div>

      <ul className="space-y-1.5 text-xs">
        {SCOPES.map(([role, scope]) => {
          const granted = RANK[user.role] >= RANK[role]
          return (
            <li key={role} className={`flex gap-2 ${granted ? 'text-ink' : 'text-muted/60'}`}>
              <span className="w-4 shrink-0 text-center">{granted ? '✓' : '–'}</span>
              <span>
                <span className="font-medium">{ROLE_LABEL[role]}</span> · {scope}
              </span>
            </li>
          )
        })}
      </ul>

      <div className="grid gap-4 border-t border-line pt-5 sm:grid-cols-2">
        <Field label="사번" hint="사번은 변경할 수 없습니다. 계정을 식별하는 기본키입니다.">
          <input value={user.employee_id} disabled className={INPUT} />
        </Field>
        <Field label="이름">
          <input value={user.name} disabled className={INPUT} />
        </Field>
        <Field label="이메일">
          <input value={user.email} disabled className={INPUT} />
        </Field>
        <Field label="부서">
          <input value={user.department || '-'} disabled className={INPUT} />
        </Field>
      </div>

      <div className="border-t border-line pt-4 text-sm">
        <span className="text-muted">마지막 비밀번호 변경 </span>
        <span className="tabular-nums">{formatTime(user.password_changed_at)}</span>
        {age !== null && (
          <span className={`ml-2 ${stale ? 'font-medium text-warn' : 'text-muted'}`}>
            ({age}일 전{stale ? ` — ${PASSWORD_WARN_DAYS}일이 지났습니다. 바꾸는 것을 권장합니다` : ''})
          </span>
        )}
      </div>
    </section>
  )
}

/** 비밀번호 변경 — 성공하면 서버가 새 세션 쿠키를 주고, 바뀐 변경일을 돌려준다. */
function PasswordForm({ onChanged }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  const mismatch = confirm.length > 0 && next !== confirm
  const tooShort = next.length > 0 && next.length < MIN_PASSWORD
  const ready = current && next.length >= MIN_PASSWORD && next === confirm && !busy

  const handleSubmit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setDone(false)
    try {
      const updated = await api.changePassword(current, next)
      onChanged(updated)
      setCurrent('')
      setNext('')
      setConfirm('')
      setDone(true)
    } catch (caught) {
      setError(caught.detail || '비밀번호를 바꾸지 못했습니다')
      setCurrent('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5">
      <h3 className="font-semibold">비밀번호 변경</h3>
      <p className="mt-0.5 text-xs text-muted">
        {MIN_PASSWORD}자 이상. 한글을 포함해 어떤 문자든 쓸 수 있습니다.
      </p>

      <form onSubmit={handleSubmit} className="mt-5 space-y-4">
        <Field label="현재 비밀번호">
          <input
            type="password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
            autoComplete="current-password"
            required
            className={INPUT}
          />
        </Field>
        <Field label="새 비밀번호" hint={tooShort ? `${MIN_PASSWORD}자 이상이어야 합니다` : undefined}>
          <input
            type="password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
            autoComplete="new-password"
            minLength={MIN_PASSWORD}
            required
            className={INPUT}
          />
        </Field>
        <Field label="새 비밀번호 확인" hint={mismatch ? '새 비밀번호와 다릅니다' : undefined}>
          <input
            type="password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            autoComplete="new-password"
            required
            className={INPUT}
          />
        </Field>

        <ErrorNote>{error}</ErrorNote>

        <div className="flex items-center gap-4">
          <button type="submit" disabled={!ready} className={BUTTON}>
            {busy ? '바꾸는 중…' : '비밀번호 바꾸기'}
          </button>
          {done && <span className="text-sm text-pass">바꿨습니다. 새 세션으로 이어집니다.</span>}
        </div>
      </form>
    </section>
  )
}

const EMPTY_FORM = { employee_id: '', name: '', email: '', department: '', role: 'engineer', password: '' }

/** 사용자 · 권한 관리 — 관리자만. 서버도 require_admin 으로 막는다. */
function UserAdmin({ me }) {
  const [users, setUsers] = useState(null)
  const [error, setError] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState(null)
  const [created, setCreated] = useState(null)
  const [busy, setBusy] = useState(null) // 처리 중인 사번 또는 'create'

  // 효과 안에서 상태를 동기적으로 바꾸지 않는다. 오류 초기화도 응답이 온 뒤에 한다.
  const load = () => {
    api
      .users()
      .then((list) => {
        setError(null)
        setUsers(list)
      })
      .catch((caught) => setError(caught.detail || '계정 목록을 불러오지 못했습니다'))
  }
  useEffect(load, [])

  const replace = (updated) =>
    setUsers((current) => current.map((item) => (item.employee_id === updated.employee_id ? updated : item)))

  const toggleActive = async (target) => {
    setBusy(target.employee_id)
    setError(null)
    try {
      replace(target.is_active ? await api.deactivateUser(target.employee_id)
                               : await api.activateUser(target.employee_id))
    } catch (caught) {
      setError(caught.detail || '상태를 바꾸지 못했습니다')
    } finally {
      setBusy(null)
    }
  }

  const update = (patch) => {
    setForm((current) => ({ ...current, ...patch }))
    setFormError(null)
  }

  const handleCreate = async (event) => {
    event.preventDefault()
    setBusy('create')
    setFormError(null)
    setCreated(null)
    try {
      const user = await api.createUser({
        ...form,
        employee_id: form.employee_id.trim(),
        name: form.name.trim(),
        email: form.email.trim(),
        department: form.department.trim() || null,
      })
      setUsers((current) => [...(current || []), user].sort((a, b) =>
        a.employee_id.localeCompare(b.employee_id)))
      setForm(EMPTY_FORM)
      setCreated(user)
    } catch (caught) {
      setFormError(caught.detail || '계정을 만들지 못했습니다')
    } finally {
      setBusy(null)
    }
  }

  const formReady =
    form.employee_id.trim() && form.name.trim() && form.email.trim() &&
    form.password.length >= MIN_PASSWORD && busy !== 'create'

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">사용자 · 권한 관리</h3>
        <p className="text-sm text-muted">
          관리자만 볼 수 있습니다. 계정을 지우는 대신 비활성화합니다 — 그 사람이 남긴 검토 이력은
          그대로 남아야 합니다.
        </p>
      </div>

      <ErrorNote onRetry={load}>{error}</ErrorNote>

      {users === null ? (
        !error && <Spinner />
      ) : users.length === 0 ? (
        <EmptyNote>계정이 없습니다.</EmptyNote>
      ) : (
        <div className="overflow-hidden rounded-xl border border-line">
          <table className="w-full text-sm">
            <thead className="bg-panel text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-3 font-medium">사번</th>
                <th className="px-4 py-3 font-medium">이름</th>
                <th className="px-4 py-3 font-medium">이메일</th>
                <th className="px-4 py-3 font-medium">부서</th>
                <th className="px-4 py-3 font-medium">권한</th>
                <th className="px-4 py-3 font-medium">상태</th>
                <th className="px-4 py-3 font-medium">비밀번호 변경</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {users.map((item) => {
                const self = item.employee_id === me.employee_id
                return (
                  <tr key={item.employee_id} className={`border-t border-line ${item.is_active ? '' : 'text-muted'}`}>
                    <td className="px-4 py-3 font-mono text-xs">{item.employee_id}</td>
                    <td className="px-4 py-3">
                      {item.name}
                      {self && <span className="ml-1.5 text-xs text-muted">(나)</span>}
                    </td>
                    <td className="px-4 py-3 text-xs">{item.email}</td>
                    <td className="px-4 py-3 text-xs">{item.department || '-'}</td>
                    <td className="px-4 py-3"><RoleBadge role={item.role} /></td>
                    <td className="px-4 py-3 text-xs">
                      {item.is_active ? <span className="text-pass">사용 중</span> : <span className="text-danger">비활성</span>}
                    </td>
                    <td className="px-4 py-3 text-xs tabular-nums">{formatTime(item.password_changed_at)}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => toggleActive(item)}
                        disabled={self || busy === item.employee_id}
                        title={self ? '자기 계정은 비활성화할 수 없습니다' : undefined}
                        className={`rounded-lg border px-3 py-1.5 text-xs transition-colors disabled:opacity-40 ${
                          item.is_active
                            ? 'border-line text-muted hover:border-danger/50 hover:text-danger'
                            : 'border-pass/40 text-pass hover:bg-pass/10'
                        }`}
                      >
                        {busy === item.employee_id ? '처리 중…' : item.is_active ? '비활성화' : '다시 활성화'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <section className="rounded-xl border border-line bg-panel p-5">
        <h4 className="font-semibold">계정 만들기</h4>
        <p className="mt-0.5 text-xs text-muted">
          초기 비밀번호를 정해 전달하고, 첫 로그인 후 본인이 바꾸도록 안내하세요. 여기 입력한
          비밀번호는 저장 뒤 다시 볼 수 없습니다.
        </p>
        <form onSubmit={handleCreate} className="mt-5 grid gap-4 sm:grid-cols-2">
          <Field label="사번" hint="만든 뒤에는 바꿀 수 없습니다">
            <input value={form.employee_id} onChange={(e) => update({ employee_id: e.target.value })}
                   maxLength={20} required className={INPUT} />
          </Field>
          <Field label="이름">
            <input value={form.name} onChange={(e) => update({ name: e.target.value })}
                   maxLength={50} required className={INPUT} />
          </Field>
          <Field label="이메일">
            <input type="email" value={form.email} onChange={(e) => update({ email: e.target.value })}
                   required className={INPUT} />
          </Field>
          <Field label="부서 (선택)">
            <input value={form.department} onChange={(e) => update({ department: e.target.value })}
                   maxLength={50} className={INPUT} />
          </Field>
          <Field label="권한">
            <select value={form.role} onChange={(e) => update({ role: e.target.value })} className={INPUT}>
              {Object.entries(ROLE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </Field>
          <Field label="초기 비밀번호" hint={`${MIN_PASSWORD}자 이상`}>
            <input type="password" value={form.password} onChange={(e) => update({ password: e.target.value })}
                   autoComplete="new-password" minLength={MIN_PASSWORD} required className={INPUT} />
          </Field>

          <div className="sm:col-span-2">
            <ErrorNote>{formError}</ErrorNote>
          </div>
          <div className="flex items-center gap-4 sm:col-span-2">
            <button type="submit" disabled={!formReady} className={BUTTON}>
              {busy === 'create' ? '만드는 중…' : '계정 만들기'}
            </button>
            {created && (
              <span className="text-sm text-pass">
                {created.employee_id} ({created.name}) 계정을 만들었습니다.
              </span>
            )}
          </div>
        </form>
      </section>
    </div>
  )
}

export default function Account() {
  const { user, setUser, can } = useAuth()

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold">계정</h2>
        <p className="text-sm text-muted">
          내 계정 정보와 비밀번호{can('admin') ? '. 관리자는 아래에서 다른 계정을 관리합니다' : ''}.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Profile user={user} />
        <PasswordForm onChanged={setUser} />
      </div>

      {can('admin') && <UserAdmin me={user} />}
    </div>
  )
}
