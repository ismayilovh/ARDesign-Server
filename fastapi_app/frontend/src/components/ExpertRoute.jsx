import { Navigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

// Mirrors AdminRoute, but requires the EXPERT role. Strictly separate from the
// admin panel: admins do not reach the evaluation queue, and non-experts (and
// anonymous visitors) are bounced to the landing page so the section isn't
// advertised to ordinary users.
export default function ExpertRoute({ children }) {
  const { user, loading } = useAuth()

  if (loading) return <div className="loading">Loading...</div>
  if (!user || user.role !== 'EXPERT') return <Navigate to="/" replace />
  return children
}