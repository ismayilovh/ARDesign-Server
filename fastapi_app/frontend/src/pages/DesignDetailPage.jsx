import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useLocation, useNavigate, Link } from 'react-router-dom'
import QRCode from 'qrcode'
import { useAuth } from '../hooks/useAuth'
import { apiFetch } from '../api/client'
import { useLocarnoTree } from '../hooks/useLocarnoTree'
import { useAuthedBlobUrl } from '../hooks/useAuthedBlobUrl'
import ActionButton from '../components/ActionButton'
import AuthedImg from '../components/AuthedImg'
import ConfirmDialog from '../components/admin/ConfirmDialog'
import EditDesignModal from '../components/EditDesignModal'
import { statusLabel, reviewStateLabel } from '../statusLabels'

const POLL_TICKS = 60

function statusClass(status) {
  return 'status status-' + status.toLowerCase()
}

/**
 * Dedicated page for a single design. Carries the owner actions (Convert/Retry,
 * Edit, Submit for evaluation, Download, Delete), an always-visible 3D viewer,
 * and a QR code. Public (approved) designs load media directly; for an owner's
 * own draft/rejected design the media is fetched with their token.
 */
export default function DesignDetailPage() {
  const { id } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const { user } = useAuth()
  const { tree } = useLocarnoTree(true)

  const [patent, setPatent] = useState(location.state?.patent ?? null)
  const [loading, setLoading] = useState(!location.state?.patent)
  const [error, setError] = useState(null)
  const [qrDataUrl, setQrDataUrl] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [show3d, setShow3d] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const pollRef = useRef(null)

  // A design is public once approved; the public list/detail sets review_state
  // to APPROVED. Treat a missing review_state (legacy/anonymous) as public too.
  const isPublic = !patent || !patent.review_state || patent.review_state === 'APPROVED'

  const fetchPatent = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/patents/${id}`)
      if (res.status === 404) throw new Error('This design no longer exists.')
      if (res.status === 403) {
        throw new Error('This registration is under evaluation. You will be able to see it again once an expert completes their review.')
      }
      if (!res.ok) throw new Error(`Failed to load design (${res.status})`)
      setPatent(await res.json())
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    fetchPatent()
  }, [fetchPatent])

  // Render the QR as soon as the model is ready, so the owner can preview a
  // draft in AR just like "View in 3D". Public designs use the plain /model URL;
  // not-yet-public ones embed a short-lived signed token (model_token) so an
  // unauthenticated scanner can still fetch the model.
  useEffect(() => {
    if (!patent || patent.status !== 'CONVERTED') {
      setQrDataUrl(null)
      return
    }
    const base = `${window.location.origin}/api/patents/${patent.id}/model`
    const url = isPublic
      ? base
      : patent.model_token
        ? `${base}?token=${patent.model_token}`
        : null
    if (!url) {
      setQrDataUrl(null)
      return
    }
    QRCode.toDataURL(url, { width: 256 })
      .then(setQrDataUrl)
      .catch(() => setQrDataUrl(null))
  }, [patent, isPublic])

  useEffect(() => {
    if (patent?.status !== 'CONVERTED') setShow3d(false)
  }, [patent?.status])

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current)
  }, [])

  const authedModelUrl = useAuthedBlobUrl(
    `/api/patents/${id}/model`,
    !!patent && !isPublic && show3d && patent.status === 'CONVERTED',
  )
  const modelSrc = isPublic ? `/api/patents/${id}/model` : authedModelUrl

  function pollStatus() {
    if (pollRef.current) return
    let count = 0
    pollRef.current = setInterval(async () => {
      count++
      if (count > POLL_TICKS) {
        clearInterval(pollRef.current)
        pollRef.current = null
        fetchPatent()
        return
      }
      try {
        const res = await apiFetch(`/api/patents/${id}/status`)
        if (!res.ok) return
        const data = await res.json()
        if (data.status === 'CONVERTED' || data.status === 'FAILED') {
          clearInterval(pollRef.current)
          pollRef.current = null
          fetchPatent()
        }
      } catch { /* retry */ }
    }, 2000)
  }

  async function handleConvert() {
    setActionError(null)
    try {
      const res = await apiFetch(`/api/patents/${id}/convert`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Failed to start conversion')
      }
      await fetchPatent()
      pollStatus()
    } catch (err) {
      setActionError(err.message)
    }
  }

  async function handleSubmit() {
    setActionError(null)
    try {
      const res = await apiFetch(`/api/patents/${id}/submit`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Could not submit for evaluation')
      }
      // It becomes obscured to the owner now, so leave the page.
      navigate('/my-submissions')
    } catch (err) {
      setActionError(err.message)
    }
  }

  async function handleDownload() {
    setActionError(null)
    try {
      const res = await apiFetch(`/api/patents/${id}/model`)
      if (!res.ok) throw new Error('Download failed')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${patent.model_filename}.glb`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setActionError('Download failed.')
    }
  }

  async function handleDelete() {
    setDeleting(true)
    try {
      const res = await apiFetch(`/api/patents/${id}`, { method: 'DELETE' })
      if (res.ok || res.status === 204) {
        navigate('/my-submissions')
        return
      }
      const err = await res.json().catch(() => ({}))
      setActionError(err.detail || 'Delete failed.')
      setConfirmDelete(false)
    } catch {
      setActionError('Delete failed.')
      setConfirmDelete(false)
    } finally {
      setDeleting(false)
    }
  }

  if (loading) {
    return (
      <div className="page">
        <p className="browse-subtitle">Loading...</p>
      </div>
    )
  }

  if (error || !patent) {
    return (
      <div className="page detail-page">
        <Link to="/browse" className="back-link">← Back to browse</Link>
        <p className="error">{error || 'Design not found.'}</p>
      </div>
    )
  }

  const isOwner = patent.user_id === user?.id
  const isConverted = patent.status === 'CONVERTED'
  const reviewState = patent.review_state
  const isEditable = isOwner && (reviewState === 'DRAFT' || reviewState === 'REJECTED')
  const canSubmit = isEditable && isConverted
  const warnings = patent.warnings ?? []
  const sourceViews = patent.source_image_views ?? []

  let mainLabel = null
  let subLabel = null
  if (tree) {
    if (patent.locarno_main_class) {
      mainLabel = tree.main_classes.find(
        (m) => m.value === patent.locarno_main_class,
      )?.label || null
    }
    if (patent.locarno_subclass && patent.locarno_main_class) {
      subLabel = (tree.subclasses_by_main[patent.locarno_main_class] || [])
        .find((s) => s.value === patent.locarno_subclass)?.label || null
    }
  }
  const locarnoLine = [mainLabel, subLabel].filter(Boolean).join(' › ')

  return (
    <div className="page detail-page">
      <Link to={isPublic ? '/browse' : '/my-submissions'} className="back-link">
        ← Back
      </Link>

      <div className="detail-header">
        <h1>{patent.model_filename}</h1>
        <span className={statusClass(patent.status)}>{statusLabel(patent.status)}</span>
        {reviewState && reviewState !== 'APPROVED' && (
          <span className={`status status-review status-review-${reviewState.toLowerCase()}`}>
            {reviewStateLabel(reviewState)}
          </span>
        )}
      </div>

      {reviewState === 'REJECTED' && (
        <section className="detail-reject-banner">
          <h3>Changes requested</h3>
          {patent.rejection_reason
            ? <p>{patent.rejection_reason}</p>
            : <p>An expert asked for changes before this design can be published.</p>}
          <p className="meta">
            Edit the registration (and replace the model if needed), reconvert,
            then submit it again for evaluation.
          </p>
        </section>
      )}

      <div className="detail-grid">
        <div className="detail-media">
          {isConverted && show3d ? (
            modelSrc ? (
              <model-viewer
                src={modelSrc}
                camera-controls
                auto-rotate
                shadow-intensity="1"
                exposure="1"
              />
            ) : (
              <div className="card-thumb card-thumb-empty"><span>Loading 3D...</span></div>
            )
          ) : patent.has_thumbnail ? (
            <div className="card-thumb">
              <AuthedImg
                path={`/api/patents/${patent.id}/thumbnail`}
                authed={!isPublic}
                alt={patent.model_filename}
              />
            </div>
          ) : (
            <div className="card-thumb card-thumb-empty">
              <span aria-hidden="true">🖼</span>
              <span>No preview</span>
            </div>
          )}
          {isConverted && !show3d && (
            <button
              type="button"
              className="view-3d-btn"
              onClick={() => setShow3d(true)}
            >
              ▶ View in 3D
            </button>
          )}
        </div>

        <aside className="detail-side">
          <div className="detail-qr">
            <h3>QR Code</h3>
            {qrDataUrl ? (
              <>
                <img src={qrDataUrl} alt="QR code linking to the 3D model" />
                <p className="qr-hint">Scan to open the 3D model</p>
              </>
            ) : (
              <p className="meta">Available once the design is converted.</p>
            )}
          </div>

          <dl className="detail-meta">
            <div>
              <dt>Type</dt>
              <dd>{patent.file_type}</dd>
            </div>
            {locarnoLine && (
              <div>
                <dt>Locarno</dt>
                <dd>{locarnoLine}</dd>
              </div>
            )}
            <div>
              <dt>Uploaded by</dt>
              <dd>{patent.uploaded_by}</dd>
            </div>
            <div>
              <dt>Uploaded</dt>
              <dd>{new Date(patent.uploaded_at).toLocaleDateString()}</dd>
            </div>
          </dl>

          <div className="card-actions detail-actions">
            {isOwner && patent.status === 'UPLOADED' && (
              <ActionButton variant="primary" onClick={handleConvert}>
                Convert
              </ActionButton>
            )}
            {isOwner && patent.status === 'FAILED' && patent.file_type !== 'IMAGE' && (
              <ActionButton variant="primary" onClick={handleConvert}>
                Retry
              </ActionButton>
            )}
            {canSubmit && (
              <ActionButton variant="primary" onClick={handleSubmit}>
                Submit for evaluation
              </ActionButton>
            )}
            {isEditable && (
              <ActionButton onClick={() => setShowEdit(true)}>Edit</ActionButton>
            )}
            {isConverted && (
              <ActionButton onClick={handleDownload}>Download</ActionButton>
            )}
            {isOwner && reviewState !== 'UNDER_REVIEW' && (
              <ActionButton variant="danger" onClick={() => setConfirmDelete(true)}>
                Delete
              </ActionButton>
            )}
          </div>
          {canSubmit && (
            <p className="meta">
              Submitting locks this registration for expert review. You will not
              be able to edit it until a decision is made.
            </p>
          )}
          {actionError && <p className="error">{actionError}</p>}
        </aside>
      </div>

      {sourceViews.length > 0 && (
        <section className="detail-sources">
          <h3>Source images</h3>
          <p className="meta">
            The reference photos this model was generated from.
          </p>
          <div className="detail-sources-grid">
            {sourceViews.map((view) => (
              <figure key={view} className="detail-source">
                <AuthedImg
                  path={`/api/patents/${patent.id}/images/${view}`}
                  authed={!isPublic}
                  alt={`${view} view`}
                />
                <figcaption>{view}</figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}

      {warnings.length > 0 && (
        <section className="detail-warnings">
          <h3>Dönüşüm uyarıları</h3>
          <p className="meta">
            Model başarıyla dönüştürüldü, ancak dönüştürücü aşağıdaki konular
            hakkında uyardı. Modeli kontrol etmenizi öneririz.
          </p>
          <ul className="warnings-list">
            {warnings.map((w, i) => (
              <li key={i} className={`warning-item warning-${w.phase}`}>
                <span className="warning-phase">
                  {w.phase === 'import' ? 'İçe aktarma' : 'Dışa aktarma'}
                </span>
                <p className="warning-message">{w.message}</p>
                {w.details && <code className="warning-details">{w.details}</code>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {showEdit && (
        <EditDesignModal
          patent={patent}
          open={showEdit}
          onClose={() => setShowEdit(false)}
          onSaved={() => { setShowEdit(false); fetchPatent() }}
        />
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this design?"
        confirmLabel="Delete"
        danger
        busy={deleting}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      >
        <p className="confirm-lead">This permanently deletes the registration and its files. This cannot be undone.</p>
      </ConfirmDialog>
    </div>
  )
}