import { NavLink } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function NavBar() {
  const { user, logout } = useAuth()

  return (
    <header className="nav-bar">
      <NavLink to="/" className="nav-brand" end>
        <span className="nav-brand-mark">AR</span>
        <span className="nav-brand-word">Design</span>
      </NavLink>

      <nav className="nav-links">
        <NavLink to="/" end className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
          Home
        </NavLink>
        <NavLink to="/browse" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
          Browse
        </NavLink>
        <NavLink to="/upload" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
          Upload
        </NavLink>
        {user && (
          <NavLink to="/my-submissions" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            My Submissions
          </NavLink>
        )}
        {user?.role === 'EXPERT' && (
          <NavLink to="/expert" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            Evaluations
          </NavLink>
        )}
        {user?.role === 'ADMIN' && (
          <NavLink to="/admin" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            Admin
          </NavLink>
        )}
      </nav>

      <div className="nav-right">
        {user ? (
          <>
            <span className="username">{user.username}</span>
            <button className="btn-logout" onClick={logout}>Sign Out</button>
          </>
        ) : (
          <>
            <NavLink to="/login" className="nav-link">Sign In</NavLink>
            <NavLink to="/register" className="nav-link">Register</NavLink>
          </>
        )}
      </div>
    </header>
  )
}
