import { useState, useEffect } from 'react'
import { getAnprCrops } from '../api'
import { Car, AlertOctagon, CheckCircle2, Shield, Eye, Scan } from 'lucide-react'

/**
 * ANPRPanel — Displays recent vehicle crops evaluated by PaddleOCR.
 * Shows OCR-read plate text, confidence %, and watchlist match badge.
 */
export default function ANPRPanel({ cameras }) {
  const [selectedCamId, setSelectedCamId] = useState('')
  const [crops, setCrops] = useState([])
  const [loading, setLoading] = useState(false)

  // Default to first camera if not set
  useEffect(() => {
    if (cameras.length > 0 && (!selectedCamId || !cameras.some((c) => c.id === selectedCamId))) {
      setSelectedCamId(cameras[0].id)
    }
  }, [cameras, selectedCamId])

  // Poll anpr-crops every 3.5 seconds
  useEffect(() => {
    if (!selectedCamId) return

    let isMounted = true

    const fetchCrops = async () => {
      try {
        const data = await getAnprCrops(selectedCamId)
        if (isMounted) setCrops(data || [])
      } catch (err) {
        // Suppress repeated logs if camera worker is temporarily offline
      } finally {
        if (isMounted) setLoading(false)
      }
    }

    fetchCrops()
    const interval = setInterval(fetchCrops, 3500)
    return () => {
      isMounted = false
      clearInterval(interval)
    }
  }, [selectedCamId])

  return (
    <div className="anpr-panel">
      <div className="anpr-header">
        <div className="anpr-title">
          <Car size={14} className="accent-icon" />
          <span>ANPR Activity</span>
          {crops.length > 0 && (
            <span className="anpr-count-badge">{crops.length}</span>
          )}
        </div>

        {cameras.length > 1 && (
          <select
            id="anpr-cam-select"
            name="anpr_cam_select"
            aria-label="Filter ANPR activity by camera"
            className="anpr-cam-select"
            value={selectedCamId}
            onChange={(e) => setSelectedCamId(e.target.value)}
          >
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id}
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="anpr-body">
        {crops.length === 0 ? (
          <div className="anpr-empty">
            <div className="anpr-scan-reticle">
              <Scan size={26} className="anpr-empty-icon" />
              <div className="reticle-corner corner-tl" />
              <div className="reticle-corner corner-tr" />
              <div className="reticle-corner corner-bl" />
              <div className="reticle-corner corner-br" />
            </div>
            <div className="anpr-empty-text">OPTICAL ANPR ARMED // MONITORING CHECKPOINT</div>
            <div className="anpr-empty-sub">
              Automatic plate OCR & watchlist correlation active for {selectedCamId || 'stream'}
            </div>
          </div>
        ) : (
          <div className="anpr-crops-list">
            {crops.map((crop, idx) => {
              const confPct = crop.confidence != null ? `${(crop.confidence * 100).toFixed(0)}%` : '—'
              const isBlacklist = crop.list_type === 'BLACKLIST'
              const isWhitelist = crop.list_type === 'WHITELIST'
              const hasMatch = crop.is_match || isBlacklist || isWhitelist

              return (
                <div key={crop.timestamp || idx} className={`anpr-card ${isBlacklist ? 'match-blacklist' : isWhitelist ? 'match-whitelist' : ''}`}>
                  <div className="anpr-crop-wrap">
                    {crop.image_base64 ? (
                      <img
                        src={`data:image/jpeg;base64,${crop.image_base64}`}
                        alt="Vehicle Crop"
                        className="anpr-crop-img"
                      />
                    ) : (
                      <div className="anpr-crop-fallback">
                        <Car size={20} />
                      </div>
                    )}
                  </div>

                  <div className="anpr-card-info">
                    <div className="anpr-plate-row">
                      <span className="anpr-plate-code">
                        {crop.plate_read || 'NO PLATE'}
                      </span>
                      {hasMatch ? (
                        <span className={`anpr-badge ${isBlacklist ? 'badge-blacklist' : 'badge-whitelist'}`}>
                          {isBlacklist ? <AlertOctagon size={11} /> : <CheckCircle2 size={11} />}
                          {crop.list_type}
                        </span>
                      ) : (
                        <span className="anpr-badge badge-neutral">
                          NO MATCH
                        </span>
                      )}
                    </div>

                    <div className="anpr-card-meta">
                      <span>Conf: {confPct}</span>
                      <span className="dot-sep">•</span>
                      <span>Track #{crop.track_id ?? '—'}</span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
