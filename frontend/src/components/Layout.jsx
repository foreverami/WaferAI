/**
 * 앱 껍데기 — 상단 헤더, 그 아래 화면 이동 탭, 그 아래 본문.
 *
 * UIUX 문서는 사이드바를 그렸지만, 여기서는 헤더 바로 아래 탭 줄로 뒀다.
 * 좁은 화면에서도 접히지 않고, 메인 화면을 먼저 보여준 뒤 이동시키는 흐름에 맞다.
 */
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { ROLE_LABEL, useAuth } from '../auth'

const TABS = [
  { to: '/', label: '대시보드', end: true },
  { to: '/review', label: '리뷰 대기열' },
  { to: '/models', label: '모델 관리', minRole: 'senior_engineer' },
  { to: '/settings', label: '설정', minRole: 'senior_engineer' },
]

export default function Layout() {
  const { user, logout, can } = useAuth()
  const navigate = useNavigate()

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const visibleTabs = TABS.filter((tab) => !tab.minRole || can(tab.minRole))

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">
              WaferAI <span className="text-brand">·</span> Fab AI Inspector
            </h1>
            <p className="text-xs text-muted">웨이퍼 결함 분류 및 엔지니어 검토</p>
          </div>

          {user && (
            <div className="flex items-center gap-4">
              <div className="text-right">
                <p className="text-sm font-medium">{user.name}</p>
                <p className="text-xs text-muted">
                  {user.employee_id} · {ROLE_LABEL[user.role] || user.role}
                </p>
              </div>
              <button
                onClick={handleLogout}
                className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:border-danger/50 hover:text-danger"
              >
                로그아웃
              </button>
            </div>
          )}
        </div>

        <nav className="mx-auto flex max-w-7xl gap-1 px-6">
          {visibleTabs.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.end}
              className={({ isActive }) =>
                `-mb-px border-b-2 px-4 py-2.5 text-sm transition-colors ${
                  isActive
                    ? 'border-brand font-medium text-ink'
                    : 'border-transparent text-muted hover:text-ink'
                }`
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">
        <Outlet />
      </main>
    </div>
  )
}
