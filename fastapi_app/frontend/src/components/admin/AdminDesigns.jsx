import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../../api/client'
import ConfirmDialog from './ConfirmDialog'
import { statusLabel, reviewStateLabel } from '../../statusLabels'

async function readError(res, fallback) {
  try {
    const body = await res.json()
    return body.detail || fallback
  } catch {
    return fallback
  }
}

export default function AdminDesigns() {
  const [designs, setDesigns] = useState([])
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [pending, setPending] = useState(null) // the design awaiting delete confirmation
  const [acting, setActing] = useState(false)

  const load = useCallback(async (search) => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (search) params.set('q', search)
      const res = await apiFetch(`/api/admin/patents?${params}`)
      if (!res.ok) throw new Error(await readError(res, 'Failed to load designs'))
      setDesigns(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load('') }, [load])

  async function runDelete() {
    if (!pending) return
    setActing(true)
    setError(null)
    try {
      const res = await apiFetch(`/api/admin/patents/${pending.id}`, { method: 'DELETE' })
      if (!res.ok && res.status !== 204) throw new Error(await readError(res, 'Delete failed'))
      setPending(null)
      await load(q)
    } catch (e) {
      setError(e.message)
      setPending(null)
    } finally {
      setActing(false)
    }
  }

  return (
    <section className="admin-section">
      <form className="admin-search" onSubmit={(e) => { e.preventDefault(); load(q) }}>
        <input
          type="text"
          placeholder="Search design name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button type="submit">Search</button>
      </form>

      {error && <div className="admin-error">{error}</div>}
      {loading ? (
        <div className="loading">Loading…</div>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>ID</th><th>Name</th><th>Owner</th><th>Type</th>
              <th>Status</th><th>Review</th><th>Locarno</th><th>Uploaded</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {designs.map((d) => (
              <tr key={d.id}>
                <td>{d.id}</td>
                <td>{d.model_filename || <em>(unnamed)</em>}</td>
                <td>{d.owner_username}</td>
                <td>{d.file_type || '-'}</td>
                <td>
                  <span className={`admin-status admin-status-${d.status}`}>{statusLabel(d.status)}</span>
                  {d.status === 'FAILED' && d.conversion_error && (
                    <span className="admin-error-hint" title={d.conversion_error}> ⓘ</span>
                  )}
                </td>
                <td>
                  <span className={`admin-status admin-review-${d.review_state}`}>
                    {reviewStateLabel(d.review_state)}
                  </span>
                </td>
                <td>{d.locarno_main_class || '-'}{d.locarno_subclass ? ` / ${d.locarno_subclass}` : ''}</td>
                <td>{new Date(d.uploaded_at).toLocaleDateString()}</td>
                <td className="admin-row-actions">
                  <button className="btn-delete" onClick={() => setPending(d)}>Delete</button>
                </td>
              </tr>
            ))}
            {designs.length === 0 && (
              <tr><td colSpan={9} className="admin-empty">No designs.</td></tr>
            )}
          </tbody>
        </table>
      )}

      <ConfirmDialog
        open={!!pending}
        title="Delete design?"
        confirmLabel="Delete design"
        danger
        busy={acting}
        onConfirm={runDelete}
        onCancel={() => setPending(null)}
      >
        {pending && (
          <p className="confirm-lead">
            Delete “{pending.model_filename || pending.id}” by {pending.owner_username}?
            This removes its files too and cannot be undone.
          </p>
        )}
      </ConfirmDialog>
    </section>
  )
}
