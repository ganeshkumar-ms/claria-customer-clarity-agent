import { useEffect, useState } from 'react'
import { getDashboard } from '../services/api'

export default function ClariaDashboardModal({ open, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [search, setSearch] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await getDashboard({
        status: statusFilter,
        severity: severityFilter,
        search,
      })
      setData(res)
    } catch (e) {
      setError(e?.message || 'Unable to load live dashboard metrics.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) load()
  }, [open, statusFilter, severityFilter])

  if (!open) return null
  const m = data?.metrics || {}
  const docs = data?.documents || []
  const activity = data?.recent_activity || []

  return (
    <div className="clariaModalBackdrop" role="dialog" aria-modal="true" aria-label="CLARIA Enterprise Dashboard">
      <div className="clariaModalCard">
        <div className="clariaModalHead">
          <div>
            <h2>CLARIA Enterprise Governance Dashboard</h2>
            <p>Live metrics backed by immutable version lineage and audit records</p>
          </div>
          <div className="clariaModalActions">
            <button type="button" className="clariaMiniBtn" onClick={load} disabled={loading}>
              {loading ? 'Refreshing...' : 'Refresh'}
            </button>
            <button type="button" className="clariaMiniBtn" onClick={onClose}>Close</button>
          </div>
        </div>

        {error && <div className="clariaDashErr">{error}</div>}

        <div className="clariaDashGrid">
          <div className="clariaDashStat"><span>Total Uploaded</span><strong>{m.total_uploaded ?? 0}</strong></div>
          <div className="clariaDashStat"><span>Redesigned</span><strong>{m.successfully_redesigned ?? 0}</strong></div>
          <div className="clariaDashStat"><span>Comparisons</span><strong>{m.comparisons_completed ?? 0}</strong></div>
          <div className="clariaDashStat"><span>Requiring Review</span><strong>{m.requiring_review ?? 0}</strong></div>
          <div className="clariaDashStat crit"><span>Critical Findings</span><strong>{m.critical_findings ?? 0}</strong></div>
          <div className="clariaDashStat warn"><span>High Findings</span><strong>{m.high_findings ?? 0}</strong></div>
          <div className="clariaDashStat ok"><span>Approved</span><strong>{m.approved_documents ?? 0}</strong></div>
          <div className="clariaDashStat"><span>Rejected</span><strong>{m.rejected_documents ?? 0}</strong></div>
        </div>

        <div className="clariaDashFilters">
          <input
            type="text"
            placeholder="Search filename or document title..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && load()}
          />
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All Statuses</option>
            <option value="Issues detected">Issues detected</option>
            <option value="Awaiting human review">Awaiting human review</option>
            <option value="Approved">Approved</option>
            <option value="Rejected">Rejected</option>
            <option value="Ready for release">Ready for release</option>
          </select>
          <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
            <option value="">All Severities</option>
            <option value="critical">Critical Findings</option>
            <option value="high">High Findings</option>
          </select>
          <button type="button" className="clariaMiniBtn" onClick={load}>Apply</button>
        </div>

        <div className="clariaDashCols">
          <div className="clariaDashSection">
            <h3>Document Registry ({docs.length})</h3>
            <div className="clariaDashTableWrap">
              <table className="clariaDashTable">
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Type</th>
                    <th>Versions</th>
                    <th>Status</th>
                    <th>Crit / High</th>
                  </tr>
                </thead>
                <tbody>
                  {docs.length === 0 ? (
                    <tr><td colSpan={5} style={{ textAlign: 'center', color: '#94a3b8' }}>No processed documents match the current filter.</td></tr>
                  ) : docs.map((d) => (
                    <tr key={d.document_id}>
                      <td><strong>{d.document_title}</strong><div className="subMeta">{d.filename}</div></td>
                      <td>{d.document_type}</td>
                      <td>v{d.versions_count}</td>
                      <td><span className="statusTag">{d.status}</span></td>
                      <td>{d.critical_findings} / {d.high_findings}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="clariaDashSection">
            <h3>Recent Audit Activity ({activity.length})</h3>
            <div className="clariaAuditFeed">
              {activity.length === 0 ? (
                <div className="subMeta">No audit events recorded yet.</div>
              ) : activity.map((a) => (
                <div key={a.event_id} className="clariaAuditItem">
                  <div className="auditHead">
                    <strong>{a.action}</strong>
                    <span>{a.timestamp}</span>
                  </div>
                  <div className="auditSub">{a.actor} ({a.role}) · {a.document_id}</div>
                  {a.details && <div className="auditDetails">{a.details}</div>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
