import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { ButtonLink } from '../components/ButtonLink'
import { Card, KV } from '../components/Card'
import { useMediaQuery } from '../hooks/useMediaQuery'

export function ScenarioEditorPage() {
  const { scenarioId } = useParams()
  const id = scenarioId || ''
  const qc = useQueryClient()
  const isMobile = useMediaQuery('(max-width: 900px)')

  const q = useQuery({
    queryKey: ['scenarioContent', id],
    queryFn: () => api.scenarios.getContent(id),
    enabled: Boolean(id),
  })

  const [text, setText] = useState<string>('{}')
  const [parseErr, setParseErr] = useState<string | null>(null)
  const [validationResult, setValidationResult] = useState<{ valid: boolean; errors: string[] } | null>(null)

  useEffect(() => {
    if (!q.data?.content) return
    setText(JSON.stringify(q.data.content, null, 2))
  }, [q.data])

  const parsed = useMemo(() => {
    try {
      const obj = JSON.parse(text)
      setParseErr(null)
      return obj as any
    } catch (e: any) {
      setParseErr(String(e?.message || e))
      return null
    }
  }, [text])

  const steps = useMemo(() => {
    const s = parsed?.steps
    return Array.isArray(s) ? s : []
  }, [parsed])

  const validate = useMutation({
    mutationFn: async () => {
      if (!parsed) throw new Error('JSON 파싱 오류를 먼저 해결하세요.')
      return api.scenarios.validate(parsed)
    },
    onSuccess: (result) => {
      setValidationResult({ valid: result.valid, errors: result.errors })
    },
  })

  const save = useMutation({
    mutationFn: async () => {
      if (!parsed) throw new Error('JSON 파싱 오류를 먼저 해결하세요.')
      // 저장 전 자동 검증 (서버에서도 검증하지만 미리 확인)
      const validation = await api.scenarios.validate(parsed)
      if (!validation.valid) {
        setValidationResult({ valid: false, errors: validation.errors })
        throw new Error('시나리오 검증 실패:\n' + validation.errors.join('\n'))
      }
      return api.scenarios.updateContent(id, parsed)
    },
    onSuccess: async () => {
      setValidationResult({ valid: true, errors: [] })
      await qc.invalidateQueries({ queryKey: ['scenarioContent', id] })
      await qc.invalidateQueries({ queryKey: ['myScenarios'] })
    },
  })

  const err = (q.error || save.error) as ApiError | null

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>시나리오 편집</h2>
        <div style={{ marginLeft: 'auto' }}>
          <ButtonLink to="/scenarios">← 내 시나리오</ButtonLink>
        </div>
      </div>

      {q.isLoading ? <div>로딩 중...</div> : null}
      {err ? <div style={{ color: 'crimson' }}>에러: {String(err.detail ?? err.message)}</div> : null}

      <section style={{ display: 'grid', gap: 10 }}>
        <Card title="요약">
          <KV label="scenario_id" value={<span className="mono">{id}</span>} />
          <KV label="name" value={q.data?.name || '-'} />
          <KV label="steps" value={String(steps.length)} />
        </Card>
      </section>

      <section style={{ display: 'grid', gap: 10 }}>
        <Card
          title="단계 미리보기"
          right={
            <div style={{ color: '#667085', fontSize: 12 }}>
              (MVP) 순서 변경/폼 편집은 다음 단계, 지금은 JSON 편집 우선
            </div>
          }
        >
          {isMobile ? (
            <div style={{ display: 'grid', gap: 10 }}>
              {steps.map((st: any, idx: number) => (
                <Card key={idx} title={`Step ${idx + 1}`} right={<span className="mono">{st?.type || '-'}</span>}>
                  <div className="mono" style={{ whiteSpace: 'pre-wrap' }}>
                    {JSON.stringify(st, null, 2)}
                  </div>
                </Card>
              ))}
            </div>
          ) : (
            <div className="tableWrap">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 60 }}>#</th>
                    <th style={{ width: 140 }}>type</th>
                    <th>payload</th>
                  </tr>
                </thead>
                <tbody>
                  {steps.map((st: any, idx: number) => (
                    <tr key={idx}>
                      <td>{idx + 1}</td>
                      <td className="mono">{st?.type || '-'}</td>
                      <td className="mono preWrap">
                        {JSON.stringify(st)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </section>

      <section style={{ display: 'grid', gap: 10 }}>
        <Card
          title="시나리오 JSON 편집"
          right={
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button
                disabled={validate.isPending || !parsed}
                onClick={() => validate.mutate()}
                style={{ fontSize: 12, padding: '6px 12px' }}
              >
                {validate.isPending ? '검증 중...' : '검증'}
              </button>
              <button disabled={save.isPending || !parsed} onClick={() => save.mutate()}>
                {save.isPending ? '저장 중...' : '저장'}
              </button>
            </div>
          }
        >
          {parseErr ? <div style={{ color: 'crimson', marginBottom: 8 }}>JSON 오류: {parseErr}</div> : null}
          {validationResult ? (
            <div
              style={{
                marginBottom: 8,
                padding: 12,
                borderRadius: 8,
                background: validationResult.valid ? '#f0fdf4' : '#fef2f2',
                border: `1px solid ${validationResult.valid ? '#86efac' : '#fca5a5'}`,
                color: validationResult.valid ? '#166534' : '#991b1b',
              }}
            >
              {validationResult.valid ? (
                <div>✓ 검증 통과: 시나리오가 올바르게 작성되었습니다.</div>
              ) : (
                <div>
                  <div style={{ fontWeight: 'bold', marginBottom: 8 }}>✗ 검증 실패:</div>
                  <ul style={{ margin: 0, paddingLeft: 20 }}>
                    {validationResult.errors.map((err, idx) => (
                      <li key={idx}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : null}
          <textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setValidationResult(null) // 입력 시 검증 결과 초기화
            }}
            style={{ width: '100%', minHeight: 360, fontFamily: 'ui-monospace, monospace', fontSize: 13 }}
          />
        </Card>
      </section>
    </div>
  )
}


