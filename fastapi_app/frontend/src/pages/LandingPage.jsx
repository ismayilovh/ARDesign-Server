import { Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function LandingPage() {
  const { user } = useAuth()

  return (
    <div className="page">
      <section className="landing-hero">
        <h1>Register your designs. Render them in 3D.</h1>
        <p className="lead">
          ARDesign turns your industrial design submissions into interactive
          3D models, properly classified under the Locarno system, ready to
          view in your browser or scan into augmented reality.
        </p>
        <div className="landing-cta">
          <Link to="/browse" className="cta-primary">Browse the catalog</Link>
          <Link to="/upload" className="cta-secondary">Register a design</Link>
        </div>
        {user?.username && (
          <p style={{ marginTop: '1.5rem', opacity: 0.85, fontSize: '0.9rem' }}>
            Welcome back, {user.username}.
          </p>
        )}
      </section>

      <section className="landing-section">
        <h2>What <span className="accent">ARDesign</span> does</h2>
        <div className="feature-grid">
          <div className="feature-card">
            <div className="feature-icon">⊞</div>
            <h3>Register</h3>
            <p>
              File a design under the WIPO Locarno classification: 32 main
              classes, over 5,000 subclasses, indexed and searchable.
            </p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">◆</div>
            <h3>Convert</h3>
            <p>
              Upload a ZIP of OBJ / STL / STP / IGES / FBX, or just front and
              side photos, and we generate a clean GLB you can view anywhere.
            </p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">⟁</div>
            <h3>Share</h3>
            <p>
              Every registered design gets a public 3D viewer URL and a QR
              code. Point a phone at it to open the model in AR.
            </p>
          </div>
        </div>
      </section>

      <section className="landing-section">
        <h2>How to <span className="accent">use it</span></h2>
        <div className="steps-list">
          <div className="step">
            <h3>Pick your input</h3>
            <p>
              ZIP up your 3D files, or take front, left, right and back
              photos of a physical sample.
            </p>
          </div>
          <div className="step">
            <h3>Classify it</h3>
            <p>
              Tell us the Locarno main class and subclass. Searchable
              dropdowns make the right one easy to find.
            </p>
          </div>
          <div className="step">
            <h3>Convert</h3>
            <p>
              We render a GLB on our infrastructure. Watch the status flip
              from <em>Queued</em> to <em>Converted</em>.
            </p>
          </div>
          <div className="step">
            <h3>Share or browse</h3>
            <p>
              Grab the QR code, or jump to <Link to="/browse">Browse</Link>
              {' '}to see designs registered by the whole community.
            </p>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        ARDesign · industrial-design registration with built-in 3D
      </footer>
    </div>
  )
}
