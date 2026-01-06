import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { getAccessToken } from '../lib/auth'

export function RequireAuth({ children }: { children: ReactNode }) {
  const nav = useNavigate()
  useEffect(() => {
    if (!getAccessToken()) nav('/login')
  }, [nav])
  return <>{children}</>
}


