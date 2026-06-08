import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api/client'
import { useLocarnoTree } from '../hooks/useLocarnoTree'
import AuthedImg from '../components/AuthedImg'
import { statusLabel, reviewStateLabel } from '../statusLabels'

function reviewClass(state) {
  return 'status status-review status-review-' + String(state || '').toLowerCase()
}

/**
 * The signed-in user's own submissions across every state. This is where an
 * owner manages drafts, sees why a design needs changes, and tracks approvals,
 * since the public catalog only shows approved designs. Submissions that are
 * under evaluation are returned obscured by the API and shown as a bare notice.
 */
export default function MySubmissionsPage() {
  const { tree } = useLocarnoTree(true)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiFetch('/api/patents/mine')
      if (!res.ok) throw new Error(`Failed to load your submissions (${res.status})`)
      setItems(await res.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  function locarnoLine(item) {
    if (!tree) return null
    let mainLabel = null
    let subLabel = null
    if (item.locarno_main_class) {
      mainLabel = tree.main_classes.find((m) => m.value === item.locarno_main_class)?.label || null
    }
    if (item.locarno_subclass && item.locarno_main_class) {
      subLabel = (tree.subclasses_by_main[item.locarno_main_class] || [])
        .find((s) => s.value === item.locarno_subclass)?.label || null
    }
    return [mainLabel, subLabel].filter(Boolean).join(' › ') || null
  }

  return (
    <div className="page">
      <h1>My submissions</h1>
      <p className="browse-subtitle">
        Your designs and where each one stands. Designs are private until an
        expert approves them.
      </p>

      {error && <p className="error">{error}</p>}

      {loading ? (
        <p className="browse-subtitle">Loading...</p>
      ) : items.length === 0 ? (
        <div className="browse-empty">
          <div className="browse-empty-icon">◌</div>
          <h3>You have not registered any designs yet</h3>
          <p>Head to <Link to="/upload">Upload</Link> to register your first design.</p>
        </div>
      ) : (
        <section className="patents-grid">
          {items.map((item) => {
            // Obscured during evaluation: the API sends only id + state + date.
            if (item.review_state === 'UNDER_REVIEW') {
              return (
                <div key={item.id} className="patent-card my-sub-card-obscured">
                  <div className="card-thumb card-thumb-empty">
                    <span aria-hidden="true">🔒</span>
                    <span>Under evaluation</span>
                  </div>
                  <h3>Registration under evaluation</h3>
                  <div className="card-status-row">
                    <span className={reviewClass(item.review_state)}>
                      {reviewStateLabel(item.review_state)}
                    </span>
                  </div>
                  <p className="meta">
                    An expert is reviewing this registration. Its details are
                    hidden until a decision is made.
                  </p>
                  {item.submitted_at && (
                    <p className="meta">
                      Submitted {new Date(item.submitted_at).toLocaleDateString()}
                    </p>
                  )}
                </div>
              )
            }

            const line = locarnoLine(item)
            const warningCount = item.warnings?.length ?? 0
            return (
              <Link
                key={item.id}
                to={`/designs/${item.id}`}
                className="patent-card patent-card-link"
              >
                {item.has_thumbnail ? (
                  <div className="card-thumb">
                    <AuthedImg
                      path={`/api/patents/${item.id}/thumbnail`}
                      authed={item.review_state !== 'APPROVED'}
                      alt={item.model_filename}
                    />
                  </div>
                ) : (
                  <div className="card-thumb card-thumb-empty">
                    <span aria-hidden="true">🖼</span>
                    <span>No preview</span>
                  </div>
                )}
                <h3>{item.model_filename}</h3>
                <div className="card-status-row">
                  <span className={reviewClass(item.review_state)}>
                    {reviewStateLabel(item.review_state)}
                  </span>
                  {item.conversion_status && item.conversion_status !== 'CONVERTED' && (
                    <span className={'status status-' + item.conversion_status.toLowerCase()}>
                      {statusLabel(item.conversion_status)}
                    </span>
                  )}
                  {warningCount > 0 && (
                    <span className="warning-badge" title={`${warningCount} converter warning(s)`}>
                      ⚠ {warningCount}
                    </span>
                  )}
                </div>
                {item.review_state === 'REJECTED' && item.rejection_reason && (
                  <p className="meta my-sub-reason">Changes requested: {item.rejection_reason}</p>
                )}
                {line && <p className="meta locarno-line">{line}</p>}
                {item.file_type && <p className="meta">Type: {item.file_type}</p>}
                {item.uploaded_at && (
                  <p className="meta">{new Date(item.uploaded_at).toLocaleDateString()}</p>
                )}
                <span className="card-open-cta">Manage →</span>
              </Link>
            )
          })}
        </section>
      )}
    </div>
  )
}