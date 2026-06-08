import { useEffect, useState } from 'react'
import { apiFetch } from '../api/client'

/**
 * An <img> whose bytes may require authentication.
 *
 * Public (approved) designs serve their thumbnail/source images to anyone, so
 * the browser can hit the URL directly. For not-yet-public designs the media
 * routes require a token (owner / expert / admin), which a raw <img src> can't
 * send - so we fetch the bytes through apiFetch and render them as a blob URL.
 *
 * Props:
 *   path: the /api/... URL to load
 *   authed: when true, fetch with the bearer token; when false, use `path` directly
 *   placeholder: rendered while the authed blob is still loading (or on failure)
 */
export default function AuthedImg({ path, authed, alt, className, placeholder = null }) {
  const [src, setSrc] = useState(authed ? null : path)

  useEffect(() => {
    if (!authed) {
      setSrc(path)
      return
    }
    let cancelled = false
    let objUrl = null
    setSrc(null)
    apiFetch(path)
      .then(async (res) => {
        if (!res.ok) return
        const blob = await res.blob()
        if (cancelled) return
        objUrl = URL.createObjectURL(blob)
        setSrc(objUrl)
      })
      .catch(() => {})
    return () => {
      cancelled = true
      if (objUrl) URL.revokeObjectURL(objUrl)
    }
  }, [path, authed])

  if (!src) return placeholder
  return <img src={src} alt={alt} className={className} loading="lazy" />
}