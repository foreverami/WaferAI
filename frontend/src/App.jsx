import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { useAuth } from './auth'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import Account from './pages/Account'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Models from './pages/Models'
import ReviewQueue from './pages/ReviewQueue'
import Settings from './pages/Settings'
import Signup from './pages/Signup'

/**
 * 로그인 문지기.
 *
 * 화면을 감추는 것은 편의지 방어가 아니다. 실제 차단은 서버가 한다.
 * 여기서는 로그인하지 않은 사용자를 로그인 화면으로 보내고, 가려던 곳을 기억한다.
 */
function RequireAuth({ children, minRole }) {
  const { user, checking, can } = useAuth()
  const location = useLocation()

  if (checking) {
    return (
      <div className="flex min-h-full items-center justify-center">
        <Spinner label="세션 확인 중" />
      </div>
    )
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  // 임시 비밀번호로 들어온 사람은 비밀번호를 바꾸기 전까지 계정 화면만 쓴다. 서버도 다른 API 를 403 으로 막는다.
  if (user.must_change_password && location.pathname !== '/account') {
    return <Navigate to="/account" replace />
  }
  if (minRole && !can(minRole)) {
    return <Navigate to="/" replace />
  }
  return children
}

export default function App() {
  const { user, checking } = useAuth()

  return (
    <Routes>
      <Route
        path="/login"
        element={!checking && user ? <Navigate to="/" replace /> : <Login />}
      />
      <Route
        path="/signup"
        element={!checking && user ? <Navigate to="/" replace /> : <Signup />}
      />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="review" element={<ReviewQueue />} />
        <Route path="account" element={<Account />} />
        <Route
          path="models"
          element={
            <RequireAuth minRole="senior_engineer">
              <Models />
            </RequireAuth>
          }
        />
        <Route
          path="settings"
          element={
            <RequireAuth minRole="senior_engineer">
              <Settings />
            </RequireAuth>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
