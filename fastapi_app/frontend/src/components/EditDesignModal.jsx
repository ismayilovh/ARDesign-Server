import { useMemo, useState } from 'react'
import { apiFetch } from '../api/client'
import { useLocarnoTree } from '../hooks/useLocarnoTree'
import Combobox from './Combobox'

// Mirrors RegistrationWizard's scale chips (backend ModelScale enum).
const SCALE_OPTIONS = [
  { value: 'MM', label: 'mm', hint: 'millimeters' },
  { value: 'CM', label: 'cm', hint: 'centimeters' },
  { value: 'M', label: 'm', hint: 'meters' },
  { value: 'IN', label: 'in', hint: 'inches' },
]

/**
 * Edit a DRAFT or REJECTED registration: rename, re-classify, change the source
 * unit, and optionally replace the model file. Staged in browser state and only
 * written on Save (PATCH /api/patents/:id, plus POST /:id/reupload when a new
 * ZIP is chosen). Replacing the file resets the design to UPLOADED so the owner
 * reconverts before resubmitting.
 */
export default function EditDesignModal({ patent, open, onClose, onSaved }) {
  const { tree, loading: treeLoading, error: treeError } = useLocarnoTree(open)

  const [designName, setDesignName] = useState(patent.model_filename || '')
  const [mainClass, setMainClass] = useState(patent.locarno_main_class || '')
  const [subclass, setSubclass] = useState(patent.locarno_subclass || '')
  const [scale, setScale] = useState(patent.scale || 'MM')
  const [file, setFile] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const isImageGen = patent.file_type === 'IMAGE'

  const mainOptions = useMemo(() => {
    if (!tree) return []
    return tree.main_classes.map((m) => ({ value: m.value, label: `Class ${m.number}: ${m.label}` }))
  }, [tree])
  const subOptions = useMemo(() => {
    if (!tree || !mainClass) return []
    return tree.subclasses_by_main[mainClass] || []
  }, [tree, mainClass])

  function handleMainChange(v) {
    setMainClass(v)
    setSubclass('')
  }

  async function handleSave() {
    if (!designName.trim()) { setError('Enter a design name.'); return }
    if (!mainClass || !subclass) { setError('Choose a Locarno main class and subclass.'); return }
    setSaving(true)
    setError(null)
    try {
      const patchRes = await apiFetch(`/api/patents/${patent.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          design_name: designName.trim(),
          locarno_main_class: mainClass,
          locarno_subclass: subclass,
          scale,
        }),
      })
      if (!patchRes.ok) {
        const err = await patchRes.json().catch(() => ({}))
        throw new Error(err.detail || 'Could not save changes.')
      }

      if (file) {
        const form = new FormData()
        form.append('file', file)
        form.append('scale', scale)
        const upRes = await apiFetch(`/api/patents/${patent.id}/reupload`, { method: 'POST', body: form })
        if (!upRes.ok) {
          const err = await upRes.json().catch(() => ({}))
          throw new Error(err.detail || 'Could not replace the model file.')
        }
      }

      onSaved?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null
  const displayError = error || treeError

  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget && !saving) onClose() }}>
      <div className="modal wizard-modal" role="dialog" aria-modal="true">
        <header className="wizard-header">
          <h2>Edit registration</h2>
        </header>

        <div className="wizard-body">
          <label className="wizard-field">
            <span>Design name</span>
            <input
              type="text"
              value={designName}
              onChange={(e) => setDesignName(e.target.value)}
              maxLength={255}
            />
          </label>
          <label className="wizard-field">
            <span>Locarno main class</span>
            <Combobox
              options={mainOptions}
              value={mainClass}
              onChange={handleMainChange}
              placeholder={treeLoading ? 'Loading...' : 'Type to filter'}
              disabled={treeLoading || !tree}
            />
          </label>
          <label className="wizard-field">
            <span>Locarno subclass</span>
            <Combobox
              options={subOptions}
              value={subclass}
              onChange={setSubclass}
              placeholder={treeLoading ? 'Loading...' : mainClass ? 'Type to filter subclasses' : 'Pick a main class first'}
              disabled={treeLoading || !mainClass}
            />
          </label>

          <div className="wizard-field">
            <span>Source unit</span>
            <div className="mv-preset-options">
              {SCALE_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className={`mv-preset-chip ${scale === opt.value ? 'active' : ''}`}
                  title={opt.hint}
                >
                  <input
                    type="radio"
                    name="edit-scale"
                    value={opt.value}
                    checked={scale === opt.value}
                    onChange={() => setScale(opt.value)}
                  />
                  {opt.label}
                </label>
              ))}
            </div>
          </div>

          {!isImageGen && (
            <label className="wizard-field">
              <span>Replace model file (optional)</span>
              <input
                type="file"
                accept=".zip"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
              {file ? (
                <p className="meta">{file.name} ({Math.round(file.size / 1024)} KB). The design will reset to Uploaded, reconvert it before resubmitting.</p>
              ) : (
                <p className="meta">Leave empty to keep the current model.</p>
              )}
            </label>
          )}
        </div>

        {displayError && <p className="error">{displayError}</p>}

        <footer className="wizard-footer">
          <button type="button" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="button" className="btn-primary" onClick={handleSave} disabled={saving || treeLoading}>
            {saving ? 'Saving...' : 'Save changes'}
          </button>
        </footer>
      </div>
    </div>
  )
}