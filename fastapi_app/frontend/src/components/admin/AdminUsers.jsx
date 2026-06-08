import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../../api/client'
import { useAuth } from '../../hooks/useAuth'
import ConfirmDialog from './ConfirmDialog'

async function readError(res, fallback) {
  try {
    const body = await res.json()
    return body.detail || fallback
  } catch {
    return fallback
  }
}

export default function AdminUsers() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState([])
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [pending, setPending] = useState(null) // { title, message, confirmLabel, danger, run }
  const [acting, setActing] = useState(false)

  const load = useCallback(async (search) => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (search) params.set('q', search)
      const res = await apiFetch(`/api/admin/users?${params}`)
      if (!res.ok) throw new Error(await readError(res, 'Failed to load users'))
      setUsers(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load('') }, [load])

  async function runPending() {
    if (!pending) return
    setActing(true)
    setError(null)
    try {
      await pending.run()
      setPending(null)
      await load(q)
    } catch (e) {
      setError(e.message)
      setPending(null)
    } finally {
      setActing(false)
    }
  }

  const ROLE_BLURB = {
    USER: 'a regular user with no admin or evaluation access',
    EXPERT: 'able to evaluate (approve/reject) design submissions, with no admin access',
    ADMIN: 'a full admin, with no evaluation access',
  }

  function confirmRole(u, role) {
    setPending({
      title: `Set ${u.username} to ${role}?`,
      message: `${u.username} will become ${ROLE_BLURB[role] || role}.`,
      confirmLabel: `Set ${role}`,
      danger: role === 'USER',
      run: async () => {
        const res = await apiFetch(`/api/admin/users/${u.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ role }),
        })
        if (!res.ok) throw new Error(await readError(res, 'Update failed'))
      },
    })
  }

  function confirmActive(u) {
    const next = !u.is_active
    setPending({
      title: `${next ? 'Activate' : 'Deactivate'} ${u.username}?`,
      message: next
        ? `${u.username} will be able to sign in again.`
        : `${u.username} will be signed out and blocked from the API immediately.`,
      confirmLabel: next ? 'Activate' : 'Deactivate',
      danger: !next,
      run: async () => {
        const res = await apiFetch(`/api/admin/users/${u.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_active: next }),
        })
        if (!res.ok) throw new Error(await readError(res, 'Update failed'))
      },
    })
  }

  function confirmDelete(u) {
    setPending({
      title: `Delete ${u.username}?`,
      message: `This permanently deletes the user and all ${u.patent_count} of their design(s), including files on disk. This cannot be undone.`,
      confirmLabel: 'Delete user',
      danger: true,
      run: async () => {
        const res = await apiFetch(`/api/admin/users/${u.id}`, { method: 'DELETE' })
        if (!res.ok && res.status !== 204) throw new Error(await readError(res, 'Delete failed'))
      },
    })
  }

  return (
    <section className="admin-section">
      <form className="admin-search" onSubmit={(e) => { e.preventDefault(); load(q) }}>
        <input
          type="text"
          placeholder="Search username or email…"
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
              <th>ID</th><th>Username</th><th>Email</th><th>Role</th>
              <th>Active</th><th>Designs</th><th>Joined</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const isSelf = u.id === me?.id
              return (
                <tr key={u.id}>
                  <td>{u.id}</td>
                  <td>{u.username}{isSelf && <span className="admin-badge">you</span>}</td>
                  <td>{u.email}</td>
                  <td>{u.role}</td>
                  <td>{u.is_active ? 'yes' : 'no'}</td>
                  <td>{u.patent_count}</td>
                  <td>{new Date(u.date_joined).toLocaleDateString()}</td>
                  <td className="admin-row-actions">
                    {['USER', 'EXPERT', 'ADMIN']
                      .filter((r) => r !== u.role)
                      .map((r) => (
                        <button key={r} disabled={isSelf} onClick={() => confirmRole(u, r)}>
                          → {r}
                        </button>
                      ))}
                    <button disabled={isSelf} onClick={() => confirmActive(u)}>
                      {u.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                    <button className="btn-delete" disabled={isSelf} onClick={() => confirmDelete(u)}>
                      Delete
                    </button>
                  </td>
                </tr>
              )
            })}
            {users.length === 0 && (
              <tr><td colSpan={8} className="admin-empty">No users.</td></tr>
            )}
          </tbody>
        </table>
      )}

      <ConfirmDialog
        open={!!pending}
        title={pending?.title}
        confirmLabel={pending?.confirmLabel}
        danger={pending?.danger}
        busy={acting}
        onConfirm={runPending}
        onCancel={() => setPending(null)}
      >
        {pending?.message && <p className="confirm-lead">{pending.message}</p>}
      </ConfirmDialog>
    </section>
  )
}
