import { useMemo, useRef, useState } from 'react'
import {
  absApiUrl,
  approveDocument,
  compareVersions,
  correctDocument,
  refineDocument,
} from '../services/api'

export default function ClariaEnterpriseWorkspace({ initialData, originalTextFallback = '' }) {
  const [bundle, setBundle] = useState(initialData)
  const [activeTab, setActiveTab] = useState('compare') // 'compare' | 'facts' | 'downloads' | 'governance'
  const [zoom, setZoom] = useState(100)
  const [syncScroll, setSyncScroll] = useState(true)
  const [changeFilter, setChangeFilter] = useState('all')
  const [selectedChange, setSelectedChange] = useState(null)
  const [refineText, setRefineText] = useState('')
  const [busy, setBusy] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')
  const [errMsg, setErrMsg] = useState('')

  // Issue decisions keyed by issue_id
  const [issueDecisions, setIssueDecisions] = useState({})
  const [editingIssueId, setEditingIssueId] = useState(null)
  const [editDraft, setEditDraft] = useState('')

  // Version comparison state
  const [cmpV1, setCmpV1] = useState(0)
  const [cmpV2, setCmpV2] = useState(bundle?.version_number || 1)
  const [verCompareData, setVerCompareData] = useState(null)

  // Governance approval state
  const [reviewerName, setReviewerName] = useState('Compliance Reviewer')
  const [reviewerRole, setReviewerRole] = useState('Compliance Reviewer')
  const [reviewComments, setReviewComments] = useState('')

  const leftPaneRef = useRef(null)
  const rightPaneRef = useRef(null)
  const lockingLeft = useRef(false)
  const lockingRight = useRef(false)

  const docId = bundle?.document_id
  const intel = bundle?.intelligence || {}
  const redesigned = bundle?.redesigned_document || {}
  const factVer = bundle?.fact_verification || {}
  const comparison = bundle?.comparison || {}
  const downloads = bundle?.downloads || {}
  const quality = bundle?.quality_validation || {}
  const gov = bundle?.governance || {}

  const changes = comparison.changes || []
  const filteredChanges = useMemo(() => {
    if (changeFilter === 'all') return changes
    if (changeFilter === 'critical_high') return changes.filter(c => c.severity === 'Critical' || c.severity === 'High')
    if (changeFilter === 'financial') return changes.filter(c => (c.category || '').toLowerCase().includes('financial') || (c.category || '').toLowerCase().includes('fact'))
    return changes.filter(c => c.highlight_color === changeFilter)
  }, [changes, changeFilter])

  const onScrollPane = (srcRef, dstRef, lockRef, otherLockRef) => {
    if (!syncScroll || !srcRef.current || !dstRef.current) return
    if (lockRef.current) { lockRef.current = false; return }
    const s = srcRef.current
    const maxS = s.scrollHeight - s.clientHeight
    if (maxS <= 0) return
    const ratio = s.scrollTop / maxS
    otherLockRef.current = true
    dstRef.current.scrollTop = ratio * (dstRef.current.scrollHeight - dstRef.current.clientHeight)
  }

  const handleRefine = async (e) => {
    e.preventDefault()
    if (!docId || !refineText.trim() || busy) return
    setBusy(true)
    setErrMsg('')
    setStatusMsg('')
    try {
      const updated = await refineDocument(docId, refineText.trim())
      setBundle(prev => ({ ...prev, ...updated }))
      setCmpV2(updated.version_number)
      setRefineText('')
      setStatusMsg(`Generated ${updated.version_label} and completed full comparison.`)
    } catch (err) {
      setErrMsg(err?.response?.data?.detail || err.message || 'Refinement failed.')
    } finally {
      setBusy(false)
    }
  }

  const handleApplyCorrections = async (confirmMode) => {
    if (!docId || busy) return
    setBusy(true)
    setErrMsg('')
    setStatusMsg('')
    try {
      const issues = comparison.actionable_issues || []
      const payloadCorrections = issues.map(iss => {
        const dec = issueDecisions[iss.issue_id] || { decision: 'approve' }
        return {
          issue_id: iss.issue_id,
          original_value: iss.original_value,
          output_value: iss.output_value,
          source_evidence: iss.source_evidence,
          source_section: iss.source_section,
          decision: dec.decision,
          edited_value: dec.edited_value,
          justification: dec.justification || '',
        }
      })
      const res = await correctDocument(docId, {
        confirm: confirmMode,
        corrections: payloadCorrections,
        actor: reviewerName || 'Editor',
      })
      if (confirmMode === 'no') {
        setBundle(prev => ({ ...prev, governance: { ...prev.governance, ...res.governance } }))
        setStatusMsg('Preserved current version and recorded your decision in the audit trail.')
      } else {
        setBundle(prev => ({ ...prev, ...res }))
        setCmpV2(res.version_number)
        setStatusMsg(`Created ${res.version_label}, revalidated facts, and updated PDF/DOCX outputs.`)
      }
    } catch (err) {
      setErrMsg(err?.response?.data?.detail || err.message || 'Correction update failed.')
    } finally {
      setBusy(false)
    }
  }

  const handleCompareVersions = async (v1Val, v2Val) => {
    if (!docId) return
    try {
      const res = await compareVersions(docId, v1Val, v2Val)
      setVerCompareData(res)
    } catch (err) {
      setErrMsg(err?.response?.data?.detail || 'Could not load version comparison.')
    }
  }

  const handleGovernanceAction = async (decision) => {
    if (!docId || busy) return
    setBusy(true)
    setErrMsg('')
    setStatusMsg('')
    try {
      const res = await approveDocument(docId, {
        decision,
        reviewer_name: reviewerName,
        reviewer_role: reviewerRole,
        comments: reviewComments,
        version_number: bundle.version_number,
      })
      setBundle(prev => ({ ...prev, governance: { ...prev.governance, ...res } }))
      setReviewComments('')
      setStatusMsg(`Governance status updated to: ${res.status}`)
    } catch (err) {
      setErrMsg(err?.response?.data?.detail || err.message || 'Governance action blocked.')
    } finally {
      setBusy(false)
    }
  }

  if (!docId) return null

  const counts = comparison.counts || {}
  const cov = comparison.coverage || {}
  const origRaw = originalTextFallback || bundle?.highlighted_document?.raw_text || ''

  return (
    <div className="clariaEntWrap">
      {/* Top Intelligence & Lineage Bar */}
      <div className="clariaEntHeader">
        <div className="clariaEntMeta">
          <span className="entBadge">{intel.document_type || 'Enterprise Document'}</span>
          <span className="entBadge version">{bundle.version_label || `Version ${bundle.version_number || 1}`}</span>
          <span className="entBadge status">{gov.status || 'Comparison completed'}</span>
          {redesigned.tone_applied && <span className="entBadge subtle">Tone: {redesigned.tone_applied}</span>}
          {redesigned.audience_applied && <span className="entBadge subtle">Audience: {redesigned.audience_applied}</span>}
        </div>
        {intel.internal_elements_count > 0 && (
          <div className="clariaInternalNotice">
            Separated {intel.internal_elements_count} internal-only block(s) from customer-facing output to prevent internal leakage.
          </div>
        )}
        {redesigned.tone_safety_warning && (
          <div className="clariaSafetyWarn">{redesigned.tone_safety_warning}</div>
        )}
      </div>

      {/* Conversational Iterative Refinement Bar */}
      <form className="clariaRefineBar" onSubmit={handleRefine}>
        <input
          type="text"
          value={refineText}
          onChange={(e) => setRefineText(e.target.value)}
          placeholder='Refine conversationally (e.g., "Make the introduction shorter", "Change tone to friendly", "Preserve the original fee table")...'
          disabled={busy}
        />
        <button type="submit" disabled={busy || !refineText.trim()}>
          {busy ? 'Updating...' : 'Apply Instruction'}
        </button>
      </form>

      {statusMsg && <div className="clariaEntOk">{statusMsg}</div>}
      {errMsg && <div className="clariaEntErr">{errMsg}</div>}

      {/* Enterprise Workspace Tabs */}
      <div className="clariaEntTabs" role="tablist">
        <button type="button" className={activeTab === 'compare' ? 'active' : ''} onClick={() => setActiveTab('compare')}>
          Side-by-Side Comparison ({counts.total_changes ?? changes.length})
        </button>
        <button type="button" className={activeTab === 'facts' ? 'active' : ''} onClick={() => setActiveTab('facts')}>
          Fact Verification &amp; Issues ({factVer.discrepancy_count ?? 0})
        </button>
        <button type="button" className={activeTab === 'downloads' ? 'active' : ''} onClick={() => setActiveTab('downloads')}>
          Downloads (PDF / DOCX)
        </button>
        <button type="button" className={activeTab === 'governance' ? 'active' : ''} onClick={() => setActiveTab('governance')}>
          Versions &amp; Governance ({(gov.versions_summary || []).length || 1})
        </button>
      </div>

      {/* TAB 1: SIDE-BY-SIDE ORIGINAL VS REDESIGNED COMPARISON */}
      {activeTab === 'compare' && (
        <div className="clariaEntPanel">
          <div className="clariaCmpToolbar">
            <div className="cmpLegend">
              <span className="legItem green"><i /> Added ({counts.added ?? 0})</span>
              <span className="legItem yellow"><i /> Modified ({counts.modified ?? 0})</span>
              <span className="legItem red"><i /> Removed / Missing ({counts.removed ?? 0})</span>
              <span className="legItem blue"><i /> Structural ({counts.structural ?? 0})</span>
            </div>
            <div className="cmpControls">
              <button type="button" className={syncScroll ? 'active' : ''} onClick={() => setSyncScroll(!syncScroll)}>
                Sync Scroll: {syncScroll ? 'ON' : 'OFF'}
              </button>
              <button type="button" onClick={() => setZoom(z => Math.max(80, z - 10))}>-</button>
              <span className="zoomPct">{zoom}%</span>
              <button type="button" onClick={() => setZoom(z => Math.min(140, z + 10))}>+</button>
            </div>
          </div>

          <div className="cmpCoverageBar">
            <span><strong>Coverage:</strong> {cov.status || 'Successfully compared'} ({cov.pages_compared || 1}/{cov.pages_total || 1} pages)</span>
            <span>{cov.pagination_note}</span>
          </div>

          <div className="clariaSplitGrid">
            <div className="clariaSplitPane">
              <div className="splitPaneHead">ORIGINAL DOCUMENT</div>
              <div
                className="splitPaneBody"
                ref={leftPaneRef}
                style={{ fontSize: `${(13.5 * zoom) / 100}px` }}
                onScroll={() => onScrollPane(leftPaneRef, rightPaneRef, lockingLeft, lockingRight)}
              >
                <pre className="plainDocPre">{origRaw}</pre>
              </div>
            </div>
            <div className="clariaSplitPane">
              <div className="splitPaneHead">REDESIGNED DOCUMENT ({bundle.version_label || 'Version 1'})</div>
              <div
                className="splitPaneBody"
                ref={rightPaneRef}
                style={{ fontSize: `${(13.5 * zoom) / 100}px` }}
                onScroll={() => onScrollPane(rightPaneRef, leftPaneRef, lockingRight, lockingLeft)}
                dangerouslySetInnerHTML={{ __html: comparison.highlighted_changes_html || `<pre class="plainDocPre">${redesigned.plain_text || ''}</pre>` }}
              />
            </div>
          </div>

          {/* Change Navigation & Inspector */}
          <div className="cmpChangeNav">
            <div className="cmpFilterRow">
              {[
                ['all', 'All Changes'],
                ['green', 'Added'],
                ['yellow', 'Modified'],
                ['red', 'Removed'],
                ['blue', 'Formatting'],
                ['financial', 'Financial'],
                ['critical_high', 'Critical & High'],
              ].map(([k, lbl]) => (
                <button key={k} type="button" className={changeFilter === k ? 'active' : ''} onClick={() => setChangeFilter(k)}>
                  {lbl}
                </button>
              ))}
            </div>
            <div className="cmpChangeList">
              {filteredChanges.slice(0, 15).map((c) => (
                <button
                  key={c.change_id}
                  type="button"
                  className={`cmpChangeRow sev-${(c.severity || 'low').toLowerCase()} ${selectedChange?.change_id === c.change_id ? 'selected' : ''}`}
                  onClick={() => setSelectedChange(c)}
                >
                  <span className={`chgDot ${c.highlight_color}`} />
                  <span className="chgId">{c.change_id}</span>
                  <span className="chgCat">{c.category}</span>
                  <span className="chgSev">{c.severity}</span>
                  <span className="chgPreview">{c.change_explanation}</span>
                </button>
              ))}
            </div>
            {selectedChange && (
              <div className="cmpInspector">
                <div><strong>{selectedChange.change_id} · {selectedChange.category} ({selectedChange.severity})</strong></div>
                <div><strong>Original (Page {selectedChange.original_page}, {selectedChange.original_section}):</strong> {selectedChange.original_text}</div>
                <div><strong>Revised (Page {selectedChange.output_page}, {selectedChange.output_section}):</strong> {selectedChange.revised_text}</div>
                <div><strong>Impact:</strong> {selectedChange.impact_assessment} · <strong>Recommended Action:</strong> {selectedChange.recommended_correction}</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 2: FACT VERIFICATION & INTERACTIVE CORRECTIONS */}
      {activeTab === 'facts' && (
        <div className="clariaEntPanel">
          <div className="factSummaryRow">
            <span>Overall Verification: <strong>{factVer.overall_status || 'Verified'}</strong></span>
            <span>Verified: <strong>{factVer.verified_count ?? 0}</strong> / {factVer.total_facts ?? 0}</span>
            <span>Discrepancies / Missing: <strong>{factVer.discrepancy_count ?? 0}</strong></span>
          </div>

          <div className="clariaDashTableWrap">
            <table className="clariaDashTable">
              <thead>
                <tr>
                  <th>Fact ID</th>
                  <th>Category</th>
                  <th>Source Value</th>
                  <th>Output Value</th>
                  <th>Source Location</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {(factVer.facts || []).length === 0 ? (
                  <tr><td colSpan={6} style={{ color: '#94a3b8' }}>No numeric financial amounts, rates, or dates extracted in source.</td></tr>
                ) : (factVer.facts || []).map((f) => (
                  <tr key={f.fact_id}>
                    <td>{f.fact_id}</td>
                    <td>{f.category}</td>
                    <td><strong>{f.extracted_value}</strong></td>
                    <td>{f.output_value || 'Missing'}</td>
                    <td>Page {f.source_page} · {f.source_section}</td>
                    <td><span className={`factStatus ${f.verification_status === 'Verified' ? 'ok' : 'warn'}`}>{f.verification_status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {(comparison.actionable_issues || []).length > 0 && (
            <div className="clariaCorrectionBox">
              <div className="corrPrompt">{comparison.correction_prompt}</div>
              {(comparison.actionable_issues || []).map((iss) => {
                const dec = issueDecisions[iss.issue_id] || { decision: 'approve' }
                return (
                  <div key={iss.issue_id} className="corrIssueCard">
                    <div className="corrIssueHead">
                      <strong>ISSUE: {iss.category} ({iss.severity})</strong>
                      <span>Page {iss.source_page} · {iss.source_section}</span>
                    </div>
                    <div className="corrVals">
                      <span>Original: <strong>{iss.original_value}</strong></span>
                      <span>Redesigned: <strong>{iss.output_value}</strong></span>
                    </div>
                    <div className="corrExplain">{iss.explanation}</div>
                    <div className="corrExplain"><em>Recommended: {iss.recommended_correction}</em></div>
                    <div className="corrBtns">
                      {['approve', 'reject', 'ignore'].map((act) => (
                        <button
                          key={act}
                          type="button"
                          className={dec.decision === act ? 'active' : ''}
                          onClick={() => setIssueDecisions(prev => ({ ...prev, [iss.issue_id]: { ...dec, decision: act } }))}
                        >
                          {act.charAt(0).toUpperCase() + act.slice(1)}
                        </button>
                      ))}
                      <button
                        type="button"
                        className={dec.decision === 'edit' ? 'active' : ''}
                        onClick={() => {
                          setEditingIssueId(iss.issue_id)
                          setEditDraft(dec.edited_value || iss.original_value || '')
                        }}
                      >
                        Edit Correction
                      </button>
                    </div>
                    {editingIssueId === iss.issue_id && (
                      <div className="corrEditRow">
                        <input value={editDraft} onChange={(e) => setEditDraft(e.target.value)} />
                        <button
                          type="button"
                          onClick={() => {
                            setIssueDecisions(prev => ({ ...prev, [iss.issue_id]: { decision: 'edit', edited_value: editDraft } }))
                            setEditingIssueId(null)
                          }}
                        >
                          Save
                        </button>
                      </div>
                    )}
                  </div>
                )
              })}
              <div className="corrFinalActions">
                <button type="button" className="btnYes" disabled={busy} onClick={() => handleApplyCorrections('yes')}>
                  YES — Apply Selected Corrections &amp; Regenerate
                </button>
                <button type="button" className="btnNo" disabled={busy} onClick={() => handleApplyCorrections('no')}>
                  NO — Preserve Current Version
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: ACTUAL DOWNLOADABLE PDF & DOCX FILES */}
      {activeTab === 'downloads' && (
        <div className="clariaEntPanel">
          <div className="clariaDlGrid">
            {[
              ['clean_pdf', 'Clean Redesigned Document (PDF)'],
              ['clean_docx', 'Clean Redesigned Document (DOCX)'],
              ['highlighted_pdf', 'Highlighted Changes Document (PDF)'],
              ['highlighted_docx', 'Highlighted Changes Document (DOCX)'],
              ['report_pdf', 'Original vs Redesigned Comparison Report (PDF)'],
              ['report_docx', 'Original vs Redesigned Comparison Report (DOCX)'],
            ].map(([k, label]) => {
              const info = downloads[k]
              const val = quality[k]
              if (!info || !info.validated) return null
              return (
                <div key={k} className="clariaDlCard">
                  <div className="dlTitle">{label}</div>
                  <div className="dlMeta">
                    {info.format} · {(info.size_bytes / 1024).toFixed(1)} KB
                    {info.page_count ? ` · ${info.page_count} page(s)` : ''}
                    {val?.valid ? ' · Quality Validated' : ''}
                  </div>
                  <div className="dlBtns">
                    <a href={absApiUrl(info.download_url)} download={info.filename} className="dlLink">Download</a>
                    {info.format === 'PDF' && (
                      <a href={absApiUrl(info.view_url)} target="_blank" rel="noreferrer" className="dlLink secondary">Preview PDF</a>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* TAB 4: VERSION LINEAGE, HUMAN APPROVAL & AUDIT TRAIL */}
      {activeTab === 'governance' && (
        <div className="clariaEntPanel">
          <div className="govBlock">
            <h4>Version Lineage &amp; Comparison</h4>
            <div className="verCompareRow">
              <select value={cmpV1} onChange={(e) => setCmpV1(Number(e.target.value))}>
                <option value={0}>Original Document</option>
                {(gov.versions_summary || []).map(v => (
                  <option key={v.version_number} value={v.version_number}>{v.version_label}</option>
                ))}
              </select>
              <span>vs</span>
              <select value={cmpV2} onChange={(e) => setCmpV2(Number(e.target.value))}>
                {(gov.versions_summary || []).map(v => (
                  <option key={v.version_number} value={v.version_number}>{v.version_label}</option>
                ))}
              </select>
              <button type="button" onClick={() => handleCompareVersions(cmpV1, cmpV2)}>Compare Versions</button>
            </div>
            {verCompareData && (
              <div className="verCmpSummary">
                <strong>{verCompareData.left_label}</strong> vs <strong>{verCompareData.right_label}</strong> —{' '}
                {verCompareData.comparison?.counts?.total_changes ?? 0} difference(s) detected.
              </div>
            )}
          </div>

          <div className="govBlock">
            <h4>Human Approval Workflow (Separation of Duties Enforced)</h4>
            <div className="govFormRow">
              <input value={reviewerName} onChange={(e) => setReviewerName(e.target.value)} placeholder="Reviewer name" />
              <select value={reviewerRole} onChange={(e) => setReviewerRole(e.target.value)}>
                <option value="Compliance Reviewer">Compliance Reviewer</option>
                <option value="Business Approver">Business Approver</option>
                <option value="Editor">Editor</option>
                <option value="Administrator">Administrator</option>
              </select>
              <input value={reviewComments} onChange={(e) => setReviewComments(e.target.value)} placeholder="Review comments..." />
            </div>
            <div className="govActionBtns">
              <button type="button" disabled={busy} onClick={() => handleGovernanceAction('submit_for_review')}>Submit for Review</button>
              <button type="button" className="btnApprove" disabled={busy} onClick={() => handleGovernanceAction('approve')}>Approve</button>
              <button type="button" className="btnReject" disabled={busy} onClick={() => handleGovernanceAction('reject')}>Reject</button>
              <button type="button" disabled={busy} onClick={() => handleGovernanceAction('release')}>Mark Ready for Release</button>
            </div>
          </div>

          <div className="govBlock">
            <h4>Model Governance &amp; Audit Trail</h4>
            {gov.model_governance && (
              <div className="modelGovLine">
                Model: <code>{gov.model_governance.model_id}</code> · Prompt: <code>{gov.model_governance.prompt_version}</code> · Processed: {gov.model_governance.processed_at}
              </div>
            )}
            <div className="clariaAuditFeed">
              {(gov.audit_trail || []).map((a) => (
                <div key={a.event_id} className="clariaAuditItem">
                  <div className="auditHead"><strong>{a.action}</strong><span>{a.timestamp}</span></div>
                  <div className="auditSub">{a.actor} ({a.role}) · v{a.version_number || 1}</div>
                  {a.details && <div className="auditDetails">{a.details}</div>}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
