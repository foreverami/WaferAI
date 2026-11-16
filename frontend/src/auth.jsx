/**
 * 로그인 상태.
 *
 * 세션은 서버의 httpOnly 쿠키가 들고 있고, 여기서는 "누가 로그인했는지" 만
 * 기억한다. 새로고침하면 `/api/auth/me` 로 다시 확인한다 — 쿠키를 읽을 수
 * 없으니 서버에 물어보는 것이 유일한 방법이고, 그래야 만료된 세션도 걸러진다.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'

import { api } from './api'
import { AuthContext } from './authContext'
import { RANK } from './roles'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    let cancelled = false
    api
      .me()
      .then((me) => !cancelled && setUser(me))
      .catch(() => !cancelled && setUser(null)) // 미로그인은 오류가 아니다
      .finally(() => !cancelled && setChecking(false))
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (employeeId, password) => {
    const me = await api.login(employeeId, password)
    setUser(me)
    return me
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({
      user,
      checking,
      login,
      logout,
      setUser,
      can: (required) => !!user && RANK[user.role] >= RANK[required],
    }),
    [user, checking, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
