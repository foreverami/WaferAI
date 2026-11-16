/** 로그인 상태 컨텍스트와 훅. 제공자(AuthProvider)는 auth.jsx 에 있다. */
import { createContext, useContext } from 'react'

export const AuthContext = createContext(null)

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth 는 AuthProvider 안에서만 쓸 수 있습니다')
  return context
}
