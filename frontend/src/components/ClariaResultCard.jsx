import { useState } from 'react'

export default function ClariaResultCard({ data, documentMetadata, onOpenDocument }) {
  const [copied, setCopied] = useState(false)
  const [showTrace, setShowTrace] = useState(false)

  if (!data) return null

  const isRedesign = data.type === 'redesign'
  if (!isRedesign) {
    const isBlocked = Boolean(
      data.guardrail_status === 'BLOCKED' ||
      data.guardrail_details?.guardrails?.status === 'BLOCKED' ||
      data.rejected ||
      (typeof data.message === 'string' && data.message.includes('🛡️'))
    )
    return (
      <div className="plain-chat">
        {isBlocked && (
          <div style={{ marginBottom: '10px' }}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '4px 12px',
                borderRadius: '999px',
                fontSize: '11.5px',
                fontWeight: 700,
                background: 'rgba(239, 68, 68, 0.22)',
                color: '#f87171',
                border: '1px solid rgba(239, 68, 68, 0.65)'
              }}
            >
              <span>🛡️</span>
              <span>
                Guardrails: Blocked (
                {data.guardrail_details?.guardrails?.triggered_rule ||
                  data.rejection_details?.reason ||
                  'Security & Privacy Violation'}
                )
              </span>
            </span>
          </div>
        )}
        <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{data.message || JSON.stringify(data)}</div>
      </div>
    )
  }

  const {
    what_this_is_about,
    what_you_need_to_do = {},
    important_details = {},
    why_this_matters,
    what_happens_next,
    simplified_communication,
    highlighted_document: highlightedDoc,
    guardrails = {},
    traceability = [],
    trace_id
  } = data

  const actionRequired = Boolean(what_you_need_to_do.action_required)
  const actionItems = what_you_need_to_do.action_items || []
  const deadline = what_you_need_to_do.deadline
  const urgency = what_you_need_to_do.urgency || 'Standard'

  const handleCopy = () => {
    if (!simplified_communication) return
    navigator.clipboard.writeText(simplified_communication)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownloadHighlighted = () => {
    if (!highlightedDoc) return
    const content = highlightedDoc.full_html || highlightedDoc.snippet_html || ''
    const blob = new Blob([content], { type: 'text/html;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = highlightedDoc.filename || 'highlighted_communication.html'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="claria-result">
      {/* 0. GUARDRAILS STATUS BAR & TOP-RIGHT TRACE ID */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
          marginBottom: '14px',
          width: '100%'
        }}
      >
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 12px',
            borderRadius: '999px',
            fontSize: '11.5px',
            fontWeight: 700,
            background: guardrails.status === 'BLOCKED'
              ? 'rgba(239, 68, 68, 0.22)'
              : guardrails.status === 'REDACTED'
              ? 'rgba(52, 211, 153, 0.16)'
              : 'rgba(52, 211, 153, 0.16)',
            color: guardrails.status === 'BLOCKED'
              ? '#f87171'
              : guardrails.status === 'REDACTED'
              ? '#34d399'
              : '#34d399',
            border: guardrails.status === 'BLOCKED'
              ? '1px solid rgba(239, 68, 68, 0.65)'
              : guardrails.status === 'REDACTED'
              ? '1px solid rgba(52, 211, 153, 0.45)'
              : '1px solid rgba(52, 211, 153, 0.45)'
          }}
        >
          <span>🛡️</span>
          <span>
            {guardrails.status === 'BLOCKED'
              ? `Guardrails: Blocked (${guardrails.triggered_rule || 'Policy Violation'})`
              : guardrails.status === 'REDACTED'
              ? `Guardrails: ${guardrails.redaction_count || 1} Secret(s) Sanitized`
              : 'Guardrails: Passed · Verified Safe'}
          </span>
        </span>

        {trace_id && (
          <span
            style={{
              fontSize: '11px',
              fontFamily: 'ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace',
              fontWeight: 600,
              color: '#38bdf8',
              letterSpacing: '0.6px',
              padding: '3px 9px',
              borderRadius: '6px',
              background: 'rgba(7, 140, 255, 0.08)',
              border: '1px solid rgba(7, 140, 255, 0.24)',
              marginLeft: 'auto',
              flexShrink: 0
            }}
            title="Verification Trace Code"
          >
            {trace_id}
          </span>
        )}
      </div>

      {/* 1. DELIVERABLE 2: WHAT YOU NEED TO DO (Action Precision Guardrail) */}
      <div className={`action-banner ${actionRequired ? 'required' : 'no-action'}`}>
        <div className="action-header">
          <span className="action-badge">
            {actionRequired ? 'Action Required' : 'Informational Only'}
          </span>
          {actionRequired && urgency && urgency !== 'None' && (
            <span className="action-urgency">URGENCY: {urgency.toUpperCase()}</span>
          )}
        </div>
        <div className="action-summary">
          {what_you_need_to_do.summary || (actionRequired ? 'Please review and take the following actions:' : '✅ No action required · This communication is for information only')}
        </div>

        {actionRequired && actionItems.length > 0 && (
          <ol className="action-items">
            {actionItems.map((item, idx) => (
              <li key={idx}><strong>Step {idx + 1}:</strong> {item}</li>
            ))}
          </ol>
        )}

        {deadline && deadline !== 'None' && (
          <div className="action-deadline">
            <span>📅 Deadline:</span>
            <strong>{deadline}</strong>
          </div>
        )}
      </div>

      {/* 2. DELIVERABLE 1: WHAT THIS IS ABOUT */}
      {what_this_is_about && (
        <div className="about-card">
          <div className="section-label">What This Is About</div>
          <p className="about-text">{what_this_is_about}</p>
        </div>
      )}

      {/* 3. DELIVERABLE 3: IMPORTANT DETAILS */}
      <div className="details-grid">
        {important_details.deadlines && important_details.deadlines.length > 0 && (
          <div className="detail-block">
            <div className="detail-title">⏰ Key Dates & Deadlines</div>
            <div className="detail-pills">
              {important_details.deadlines.map((d, i) => (
                <div key={i} className="detail-pill">• {d}</div>
              ))}
            </div>
          </div>
        )}

        {important_details.amounts && important_details.amounts.length > 0 && (
          <div className="detail-block">
            <div className="detail-title">💰 Amounts & Charges</div>
            <div className="detail-pills">
              {important_details.amounts.map((a, i) => (
                <div key={i} className="detail-pill">• {a}</div>
              ))}
            </div>
          </div>
        )}

        {important_details.required_documents && important_details.required_documents.length > 0 && (
          <div className="detail-block">
            <div className="detail-title">📄 Required Documents</div>
            <div className="detail-pills">
              {important_details.required_documents.map((doc, i) => (
                <div key={i} className="detail-pill">• {doc}</div>
              ))}
            </div>
          </div>
        )}

        {important_details.warnings && important_details.warnings.length > 0 && (
          <div className="detail-block">
            <div className="detail-title">⚠️ Warnings & Consequences</div>
            <div className="detail-pills">
              {important_details.warnings.map((w, i) => (
                <div key={i} className="detail-pill">• {w}</div>
              ))}
            </div>
          </div>
        )}

        {important_details.contact_info && important_details.contact_info.length > 0 && (
          <div className="detail-block">
            <div className="detail-title">📞 Contact & Verification</div>
            <div className="detail-pills">
              {important_details.contact_info.map((c, i) => (
                <div key={i} className="detail-pill">• {c}</div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 4. DELIVERABLES 4 & 5: WHY THIS MATTERS & WHAT HAPPENS NEXT */}
      {(why_this_matters || what_happens_next) && (
        <div className="impact-columns">
          {why_this_matters && (
            <div className="impact-card">
              <div className="section-label">Why This Matters</div>
              <p>{why_this_matters}</p>
            </div>
          )}
          {what_happens_next && (
            <div className="impact-card">
              <div className="section-label">What Happens Next</div>
              <p>{what_happens_next}</p>
            </div>
          )}
        </div>
      )}

      {/* 5. DELIVERABLE 6: SIMPLIFIED COMMUNICATION */}
      {simplified_communication && (
        <div className="simplified-card">
          <div className="simplified-header">
            <div className="section-label" style={{ color: '#38bdf8', marginBottom: 0 }}>
              Simplified Customer Communication
            </div>
            <button className="copy-btn" onClick={handleCopy} type="button">
              {copied ? '✓ COPIED TO CLIPBOARD' : '📋 COPY SIMPLIFIED TEXT'}
            </button>
          </div>
          <div className="simplified-body">{simplified_communication}</div>
        </div>
      )}

      {/* HIGHLIGHTED ORIGINAL DOCUMENT (100% VERBATIM PRESERVED) */}
      {highlightedDoc && (
        <div className="highlighted-doc-card">
          <div className="highlighted-doc-header">
            <div className="highlighted-doc-title">
              <span className="doc-icon">📄</span>
              <div>
                <strong>Highlighted Original Communication (Output File)</strong>
                <div className="highlighted-doc-sub">100% Word-for-Word Original Input Preserved • Important Things Highlighted in Big Distinct Colors</div>
              </div>
            </div>
            <div className="highlighted-doc-actions">
              <button
                type="button"
                className="doc-action-btn primary"
                onClick={handleDownloadHighlighted}
                title="Download original file with big color-coded highlights"
              >
                📥 Download Highlighted File (.html)
              </button>
              {onOpenDocument && (
                <button
                  type="button"
                  className="doc-action-btn"
                  onClick={() => onOpenDocument({
                    filename: highlightedDoc.filename || 'highlighted_notice.html',
                    view_url: highlightedDoc.view_url,
                    url: highlightedDoc.download_url
                  })}
                >
                  👁️ Open in Side Viewer ↗
                </button>
              )}
            </div>
          </div>

          <div className="highlight-legend-bar">
            <span className="legend-label">Highlight Legend:</span>
            <span className="claria-hl-action">Action Required</span>
            <span className="claria-hl-deadline">Deadline &amp; Date</span>
            <span className="claria-hl-amount">Amount &amp; Penalty</span>
            <span className="claria-hl-reference">Reference &amp; Contact</span>
          </div>

          {highlightedDoc.snippet_html && (
            <div
              className="highlighted-verbatim-body"
              dangerouslySetInnerHTML={{ __html: highlightedDoc.snippet_html }}
            />
          )}
        </div>
      )}

      {/* 6. SOURCE AUDIT & TRACEABILITY */}
      {traceability && traceability.length > 0 && (
        <div className="guardrails-footer" style={{ justifyContent: 'flex-end' }}>
          <button
            type="button"
            className="copy-btn"
            style={{ fontSize: '10px', padding: '4px 10px' }}
            onClick={() => setShowTrace(!showTrace)}
          >
            {showTrace ? 'Hide Source Quotes ▲' : `Source Traceability (${traceability.length} points) ▼`}
          </button>
        </div>
      )}

      {showTrace && traceability && traceability.length > 0 && (
        <div className="trace-details">
          <div className="section-label" style={{ fontSize: '8.5px', marginBottom: '8px' }}>
            Verified Source Traceability Links
          </div>
          {traceability.map((item, idx) => (
            <div key={idx} className="trace-item">
              <strong>{item.key_point}</strong>
              <span className="trace-quote">“{item.source_excerpt}”</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

