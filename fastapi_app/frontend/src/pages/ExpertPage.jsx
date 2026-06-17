import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiFetch } from '../api/client'
import { useLocarnoTree } from '../hooks/useLocarnoTree'
import { useAuthedBlobUrl } from '../hooks/useAuthedBlobUrl'
import Combobox from '../components/Combobox'
import AuthedImg from '../components/AuthedImg'
import ActionButton from '../components/ActionButton'
import ConfirmDialog from '../components/admin/ConfirmDialog'

const PAGE_SIZE = 50
const SEARCH_DEBOUNCE_MS = 250

function locarnoLabels(tree, item) {
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

/**
 * Inspect panel for one pending submission: 3D viewer (model bytes fetched with
 * the expert's token), metadata, source images, and the approve/reject actions.
 */
function InspectModal({ submission, tree, onClose, onDecided }) {
  const [error, setError] = useState(null)
  const [acting, setActing] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')

  const modelUrl = useAuthedBlobUrl(
    `/api/patents/${submission.id}/model`,
    submission.conversion_status === 'CONVERTED',
  )
  const line = locarnoLabels(tree, submission)
  const warnings = submission.warnings ?? []
  const sourceViews = submission.source_image_views ?? []

  async function decide(path, body) {
    setActing(true)
    setError(null)
    try {
      const res = await apiFetch(`/api/expert/submissions/${submission.id}/${path}`, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Could not record the decision.')
      }
      onDecided()
    } catch (err) {
      setError(err.message)
      setRejecting(false)
    } finally {
      setActing(false)
    }
  }

  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget && !acting) onClose() }}>
      <div className="modal expert-inspect" role="dialog" aria-modal="true">
        <header className="detail-header">
          <h2>{submission.model_filename}</h2>
        </header>

        <div className="detail-grid">
          <div className="detail-media">
            {modelUrl ? (
              <model-viewer src={modelUrl} camera-controls auto-rotate shadow-intensity="1" exposure="1" />
            ) : submission.has_thumbnail ? (
              <div className="card-thumb">
                <AuthedImg path={`/api/patents/${submission.id}/thumbnail`} authed alt={submission.model_filename} />
              </div>
            ) : (
              <div className="card-thumb card-thumb-empty"><span>Loading model...</span></div>
            )}
          </div>

          <aside className="detail-side">
            <dl className="detail-meta">
              <div><dt>Owner</dt><dd>{submission.owner_username}</dd></div>
              {submission.owner_email && <div><dt>Email</dt><dd>{submission.owner_email}</dd></div>}
              <div><dt>Type</dt><dd>{submission.file_type}</dd></div>
              {line && <div><dt>Locarno</dt><dd>{line}</dd></div>}
              <div><dt>Submitted</dt><dd>{new Date(submission.submitted_at).toLocaleString()}</dd></div>
            </dl>

            <div className="card-actions detail-actions">
              <ActionButton variant="primary" onClick={() => decide('approve')}>Approve</ActionButton>
              <ActionButton variant="danger" onClick={() => setRejecting(true)}>Reject</ActionButton>
            </div>
            {error && <p className="error">{error}</p>}
          </aside>
        </div>

        {sourceViews.length > 0 && (
          <section className="detail-sources">
            <h3>Source images</h3>
            <div className="detail-sources-grid">
              {sourceViews.map((view) => (
                <figure key={view} className="detail-source">
                  <AuthedImg path={`/api/patents/${submission.id}/images/${view}`} authed alt={`${view} view`} />
                  <figcaption>{view}</figcaption>
                </figure>
              ))}
            </div>
          </section>
        )}

        {warnings.length > 0 && (
          <section className="detail-warnings">
            <h3>Converter warnings</h3>
            <ul className="warnings-list">
              {warnings.map((w, i) => (
                <li key={i} className={`warning-item warning-${w.phase}`}>
                  <span className="warning-phase">{w.phase}</span>
                  <p className="warning-message">{w.message}</p>
                  {w.details && <code className="warning-details">{w.details}</code>}
                </li>
              ))}
            </ul>
          </section>
        )}

        <footer className="wizard-footer">
          <button type="button" onClick={onClose} disabled={acting}>Close</button>
        </footer>
      </div>

      <ConfirmDialog
        open={rejecting}
        title="Reject this submission?"
        confirmLabel="Reject"
        danger
        busy={acting}
        onConfirm={() => { if (reason.trim()) decide('reject', { reason: reason.trim() }) }}
        onCancel={() => setRejecting(false)}
      >
        <p className="confirm-lead">
          Explain what needs to change. The owner sees this reason and can edit
          and resubmit the registration.
        </p>
        <textarea
          className="reject-reason-input"
          rows={4}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason for rejection"
          maxLength={2000}
        />
      </ConfirmDialog>
    </div>
  )
}

/**
 * Expert evaluation queue. Shared across experts: any expert can open and
 * decide any pending submission. Searchable by name and Locarno classification.
 */
export default function ExpertPage() {
  const { tree, loading: treeLoading } = useLocarnoTree(true)

  const [searchInput, setSearchInput] = useState('')
  const [mainClass, setMainClass] = useState('')
  const [subclass, setSubclass] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [searchInput])

  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)

  const mainOptions = useMemo(() => {
    if (!tree) return []
    return tree.main_classes.map((m) => ({ value: m.value, label: `Class ${m.number}: ${m.label}` }))
  }, [tree])
  const subOptions = useMemo(() => {
    if (!tree || !mainClass) return []
    return tree.subclasses_by_main[mainClass] || []
  }, [tree, mainClass])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (debouncedSearch) params.set('q', debouncedSearch)
      if (mainClass) params.set('locarno_main', mainClass)
      if (subclass) params.set('locarno_subclass', subclass)
      params.set('limit', String(PAGE_SIZE))
      const res = await apiFetch(`/api/expert/submissions?${params.toString()}`)
      if (!res.ok) throw new Error(`Failed to load the queue (${res.status})`)
      setItems(await res.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [debouncedSearch, mainClass, subclass])

  useEffect(() => { load() }, [load])

  function handleMainChange(v) {
    setMainClass(v)
    setSubclass('')
  }

  function onDecided() {
    setSelected(null)
    load()
  }

  return (
    <div className="page">
      <h1>Evaluation queue</h1>
      <p className="browse-subtitle">
        Registrations awaiting your decision, oldest first.
      </p>

      <div className="browse-filters expert-filters">
        <label>
          <span>Search by name</span>
          <input type="text" value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Start typing..." />
        </label>
        <label>
          <span>Locarno main class</span>
          <Combobox options={mainOptions} value={mainClass} onChange={handleMainChange} placeholder={treeLoading ? 'Loading...' : 'Any class'} disabled={treeLoading || !tree} />
        </label>
        <label>
          <span>Locarno subclass</span>
          <Combobox options={subOptions} value={subclass} onChange={setSubclass} placeholder={mainClass ? 'Any subclass' : 'Pick a main class first'} disabled={treeLoading || !mainClass} />
        </label>
      </div>

      {error && <p className="error">{error}</p>}

      {loading ? (
        <p className="browse-subtitle">Loading...</p>
      ) : items.length === 0 ? (
        <div className="browse-empty">
          <div className="browse-empty-icon">◌</div>
          <h3>Nothing to evaluate</h3>
          <p>There are no submissions awaiting a decision.</p>
        </div>
      ) : (
        <section className="patents-grid">
          {items.map((item) => {
            const line = locarnoLabels(tree, item)
            return (
              <div
                key={item.id}
                className="patent-card patent-card-link"
                role="button"
                tabIndex={0}
                onClick={() => setSelected(item)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(item) }
                }}
              >
                {item.has_thumbnail ? (
                  <div className="card-thumb">
                    <AuthedImg path={`/api/patents/${item.id}/thumbnail`} authed alt={item.model_filename} />
                  </div>
                ) : (
                  <div className="card-thumb card-thumb-empty">
                    <span aria-hidden="true">🖼</span>
                    <span>No preview</span>
                  </div>
                )}
                <h3>{item.model_filename}</h3>
                {line && <p className="meta locarno-line">{line}</p>}
                <p className="meta">By: {item.owner_username}</p>
                {item.file_type && <p className="meta">Type: {item.file_type}</p>}
                <p className="meta">Submitted {new Date(item.submitted_at).toLocaleDateString()}</p>
                <span className="card-open-cta">Evaluate →</span>
              </div>
            )
          })}
        </section>
      )}

      {selected && (
        <InspectModal
          submission={selected}
          tree={tree}
          onClose={() => setSelected(null)}
          onDecided={onDecided}
        />
      )}
    </div>
  )
}