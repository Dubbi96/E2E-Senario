import type { ReactNode } from 'react'
import { createContext, useCallback, useContext, useMemo, useState } from 'react'

type ToastKind = 'info' | 'success' | 'error'

type Toast = {
  id: string
  kind: ToastKind
  title?: string
  message: string
  createdAt: number
  timeoutMs: number
}

type ToastInput = Omit<Toast, 'id' | 'createdAt' | 'timeoutMs'> & { id?: string; createdAt?: number; timeoutMs?: number }

type ToastCtx = {
  push: (t: ToastInput) => string
  remove: (id: string) => void
}

const Ctx = createContext<ToastCtx | null>(null)

function uid() {
  return `${Date.now()}_${Math.random().toString(16).slice(2)}`
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const remove = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const push = useCallback(
    (t: ToastInput) => {
      const id = t.id || uid()
      const toast: Toast = {
        id,
        kind: t.kind || 'info',
        title: t.title,
        message: t.message,
        createdAt: t.createdAt || Date.now(),
        timeoutMs: t.timeoutMs || 4000,
      }
      setToasts((prev) => [toast, ...prev].slice(0, 5))
      window.setTimeout(() => remove(id), toast.timeoutMs)
      return id
    },
    [remove],
  )

  const value = useMemo(() => ({ push, remove }), [push, remove])

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="toastWrap" aria-live="polite" aria-atomic="true">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            <div className="toastTop">
              <div className="toastTitle">{t.title || (t.kind === 'error' ? '오류' : t.kind === 'success' ? '성공' : '알림')}</div>
              <button className="toastClose" onClick={() => remove(t.id)} aria-label="close">
                ✕
              </button>
            </div>
            <div className="toastMsg">{t.message}</div>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}

export function useToast() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}


