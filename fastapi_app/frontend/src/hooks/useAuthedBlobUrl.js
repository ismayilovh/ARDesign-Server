import { useEffect, useState } from 'react'
import { apiFetch } from '../api/client'

/**
 * Fetch a media URL that may require auth (e.g. a not-yet-public design's GLB)
 * and expose it as a blob object URL, revoked on cleanup. When `enabled` is
 * false it returns null - callers use the direct URL for public designs so QR
 * scans and anonymous viewers keep working without a token.
 */
export function useAuthedBlobUrl(path, enabled) {
  const [url, setUrl] = useState(null)
  useEffect(() => {
    if (!enabled) {
      setUrl(null)
      return
    }
    let cancelled = false
    let objUrl = null
    apiFetch(path)
      .then(async (res) => {
        if (!res.ok) return
        const blob = await res.blob()
        if (cancelled) return
        objUrl = URL.createObjectURL(blob)
        setUrl(objUrl)
      })
      .catch(() => {})
    return () => {
      cancelled = true
      if (objUrl) URL.revokeObjectURL(objUrl)
    }
  }, [path, enabled])
  return url
}