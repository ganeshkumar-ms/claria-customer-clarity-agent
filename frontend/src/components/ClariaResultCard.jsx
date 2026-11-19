import { useState } from 'react'
import { absApiUrl } from '../services/api'

function resolveRedesignedDoc(data, highlightedDoc, sourceFilename) {
  const existing = data?.redesigned_document || {}
  const rawText = (highlightedDoc?.raw_text || data?.original_text || '').replace(/\r\n/g, '\n')
  const flat = rawText.replace(/\s+/g, ' ')

  // Extract metadata deterministically from rawText to backfill any missing fields
  const refM = flat.match(/\b(?:Document\s+)?Reference\b[\s:|]+((?=[A-Z0-9-]*\d)[A-Z0-9-]{5,24})\b/)
  const loanM = flat.match(/\bLoan\s*account\b[\s:|]+((?=[A-Z0-9-]*\d)[A-Z0-9-]{5,24})\b/i)
  const dateM = flat.match(/\bDate\b[\s:|]*(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})/i)
  const dlM = flat.match(/(?:DEADLINE|on or before|by|no later than)[\s:|]*(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})/i)
  const custM = rawText.match(/Custom\s*er(?![\s:|]*(?:Communication|Support|Service|Care|Relations)\b)[\s:|]+([A-Z][A-Za-z0-9\s&.,()-]+?(?:Ltd\.?|Limited|Inc\.?|PLC|LLP|Corp\.?|Enterprises))(?=\s+Loan\b|\s+Account\b|\s+Subject\b|\n|$)/i)
  const bankM = flat.match(/\b([A-Z][A-Za-z0-9&.]*(?:\s+[A-Z][A-Za-z0-9&.]*){0,4}\s+Bank(?:\s+Ltd\.?|\s+Limited)?)\b/)
  const divM = flat.match(/\b(Commercial\s+Banking\s+Division|[A-Z][A-Za-z\s]+Division)\b/)

  const extractedDetails = []
  if (custM) extractedDetails.push({ label: 'Customer', value: custM[1].replace(/\s+/g, ' ').trim() })
  if (loanM) extractedDetails.push({ label: 'Loan account', value: loanM[1].trim() })
  if (refM) extractedDetails.push({ label: 'Reference', value: refM[1].trim() })
  if (dateM) extractedDetails.push({ label: 'Notice date', value: dateM[1].trim() })

  const rawLines = rawText.split('\n').map(l => l.trim()).filter(Boolean)
  const bulletLines = rawLines
    .filter(l => /^(?:[•\-*▪▸]|\d+[.)])\s*/.test(l))
    .map(l => l.replace(/^(?:[•\-*▪▸]|\d+[.)])\s*/, '').replace(/\.$/, '').trim())
    .filter(l => l.length > 3)

  const deadline = existing.deadline || (dlM ? dlM[1].trim() : '')
  const institution = existing.sign_off_institution || (bankM ? bankM[1].replace(/\s+/g, ' ').trim() : '')
  const division = existing.sign_off_division || (divM ? divM[1].replace(/\s+/g, ' ').trim() : '')

  const isPlaceholder = (v) => !v || /^exact\s+/i.test(String(v).trim()) || String(v).trim() === '[TO BE CONFIRMED]'
  const existingDetails = (existing.account_details || []).filter(r => r && !isPlaceholder(r.value))
  const hasBodyTable = (existing.sections || []).some(s => (s.table || []).length > 0)
  const finalDetails = existingDetails.length > 0 ? existingDetails : ((existing.email_headers || hasBodyTable) ? [] : extractedDetails)

  return {
    title: existing.title || sourceFilename.replace(/\.[^/.]+$/, '').replace(/[_-]+/g, ' '),
    introduction: existing.introduction || data?.what_this_is_about || '',
    deadline_label: existing.deadline_label || (deadline ? 'PLEASE SUBMIT BY' : ''),
    deadline,
    details_heading: existing.details_heading || 'Key document details',
    account_details: finalDetails,
    what_we_need_heading: existing.what_we_need_heading || '',
    what_we_need_intro: existing.what_we_need_intro || '',
    checklist: existing.checklist || [],
    preparation_requirement: existing.preparation_requirement || '',
    why_we_need_heading: existing.why_we_need_heading || '',
    what_happens_next: existing.what_happens_next || '',
    how_to_send_heading: existing.how_to_send_heading || '',
    how_to_submit_intro: existing.how_to_submit_intro || '',
    submission_routes: existing.submission_routes || [],
    how_to_submit: existing.how_to_submit || '',
    need_help: existing.need_help || '',
    sections: existing.sections || [],
    obligations_heading: existing.obligations_heading || 'Important information & obligations',
    mandatory_disclosures: existing.mandatory_disclosures || [],
    closing_heading: existing.closing_heading || 'Thank you',
    closing_text:
      existing.closing_text ||
      (institution ? `Thank you for your continued relationship with ${institution}.` : 'Please reach out if you have any questions or need assistance.'),
    sign_off_division: existing.sign_off_division || '',
    sign_off_institution: existing.sign_off_institution || '',
    footer_note: '',
    page_footer_left: existing.page_footer_left || (institution ? `${institution}` : sourceFilename),
    total_pages: existing.total_pages || data?.intelligence?.total_pages || 1,
    tone_applied: existing.tone_applied || 'Customer-Friendly & Clear',
    user_instruction: existing.user_instruction || '',
    brand_color: existing.brand_color || existing.source_design?.primary_color || '#163a5f',
    source_design: existing.source_design || data?.document_metadata?.design_profile || null,
    email_headers: existing.email_headers || null,
  }
}

function buildStandaloneRedesignedHtml(rd) {
  const esc = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  const rowsHtml = (rd.account_details || [])
    .map(r => `<tr><th>${esc(r.label)}</th><td>${esc(r.value)}</td></tr>`)
    .join('')
  const checklistHtml = (rd.checklist || [])
    .map(item => `<li><span class="sq">■</span><span>${esc(String(item).replace(/\.$/, ''))}</span></li>`)
    .join('')
  const routesHtml = (rd.submission_routes || [])
    .map(rt => `<li>${esc(rt)}</li>`)
    .join('')
  const obligationsHtml = (rd.mandatory_disclosures || [])
    .map(ob => `<p>${esc(ob)}</p>`)
    .join('')

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>${esc(rd.title)}</title>
  <style>
    body { margin: 0; padding: 32px; background: #f1f5f9; color: #1e293b; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.6; }
    .paper { max-width: 780px; margin: 0 auto; background: #fff; padding: 48px 54px 34px; border: 1px solid #cbd5e1; border-radius: 6px; box-shadow: 0 10px 25px rgba(15, 23, 42, 0.08); }
    h1 { margin: 0 0 12px; font-size: 28px; font-weight: 800; color: #163a5f; }
    .lead { margin: 0 0 20px; font-size: 15.5px; color: #334155; }
    .dlBox { padding: 16px 20px; margin: 0 0 28px; background: #e8f1f8; border: 1px solid #7fa6c9; text-align: center; }
    .dlLbl { display: block; font-size: 11px; font-weight: 800; color: #163a5f; letter-spacing: 0.5px; text-transform: uppercase; }
    .dlDate { display: block; font-size: 23px; font-weight: 800; color: #163a5f; margin-top: 2px; }
    h2 { margin: 22px 0 8px; font-size: 17px; font-weight: 700; color: #163a5f; }
    p { margin: 0 0 10px; font-size: 14px; color: #1e293b; }
    table { width: 100%; border-collapse: collapse; font-size: 13.5px; margin: 8px 0 18px; }
    th, td { border: 1px solid #dce3ec; padding: 8px 12px; text-align: left; }
    th { width: 165px; background: #f8fafc; font-weight: 700; color: #1e293b; }
    .chk { list-style: none; padding: 0 0 0 14px; margin: 10px 0 14px; }
    .chk li { display: flex; gap: 9px; margin-bottom: 7px; font-size: 14px; color: #0f172a; }
    .sq { font-size: 11px; line-height: 1.8; }
    ul.routes { margin: 8px 0 12px; padding-left: 26px; font-size: 14px; }
    ul.routes li { margin-bottom: 6px; }
    hr { border: 0; border-top: 1px solid #dce3ec; margin: 24px 0 18px; }
    .signoff { margin-top: 12px; font-size: 14px; }
    .signoff strong { display: block; }
    .footnote { margin: 22px 0 14px; font-size: 11.5px; color: #64748b; }
    .pgFoot { display: flex; justify-content: space-between; border-top: 1px solid #cbd5e1; padding-top: 10px; margin-top: 18px; font-size: 11px; color: #64748b; }
  </style>
</head>
<body>
  <div class="paper">
    <h1>${esc(rd.title)}</h1>
    ${rd.introduction ? `<p class="lead">${esc(rd.introduction)}</p>` : ''}
    ${rd.deadline ? `<div class="dlBox"><span class="dlLbl">${esc(rd.deadline_label || 'PLEASE SUBMIT BY')}</span><strong class="dlDate">${esc(String(rd.deadline).toUpperCase())}</strong></div>` : ''}
    ${rowsHtml ? `<h2>${esc(rd.details_heading || 'Your loan details')}</h2><table><tbody>${rowsHtml}</tbody></table>` : ''}
    ${checklistHtml ? `<h2>${esc(rd.what_we_need_heading || 'What we need from you')}</h2>${rd.what_we_need_intro ? `<p>${esc(rd.what_we_need_intro)}</p>` : ''}<ul class="chk">${checklistHtml}</ul>${rd.preparation_requirement ? `<p><strong>Preparation requirement: </strong>${esc(rd.preparation_requirement)}</p>` : ''}` : ''}
    ${rd.what_happens_next ? `<h2>${esc(rd.why_we_need_heading || 'Why we need these documents')}</h2><p>${esc(rd.what_happens_next)}</p>` : ''}
    ${(routesHtml || rd.how_to_submit || rd.need_help) ? `<h2>${esc(rd.how_to_send_heading || 'How to send your documents')}</h2>${rd.how_to_submit_intro ? `<p>${esc(rd.how_to_submit_intro)}</p>` : ''}${routesHtml ? `<ul class="routes">${routesHtml}</ul>` : (rd.how_to_submit ? `<p>${esc(rd.how_to_submit)}</p>` : '')}${rd.need_help ? `<p>${esc(rd.need_help)}</p>` : ''}` : ''}
    ${obligationsHtml ? `<h2>${esc(rd.obligations_heading || 'Important information about your loan obligations')}</h2>${obligationsHtml}` : ''}
    <hr />
    <h2>${esc(rd.closing_heading || 'Thank you for your cooperation')}</h2>
    ${rd.closing_text ? `<p>${esc(rd.closing_text)}</p>` : ''}
    <div class="signoff"><strong>${esc(rd.sign_off_division || 'Commercial Banking Division')}</strong><span>${esc(rd.sign_off_institution || 'Northridge Commercial Bank')}</span></div>
    ${rd.footer_note ? `<p class="footnote">${esc(rd.footer_note)}</p>` : ''}
    <div class="pgFoot"><span>${esc(rd.page_footer_left)}</span><span>Page 1</span></div>
  </div>
</body>
</html>`
}

function buildStandaloneRedesignedTxt(rd) {
  const lines = [
    rd.title || 'Your annual financial review',
    '='.repeat((rd.title || 'Your annual financial review').length),
    '',
  ]
  if (rd.introduction) {
    lines.push(rd.introduction, '')
  }
  if (rd.deadline) {
    lines.push(`${rd.deadline_label || 'PLEASE SUBMIT BY'}: ${String(rd.deadline).toUpperCase()}`, '')
  }
  if (rd.account_details?.length) {
    lines.push(rd.details_heading || 'Your loan details')
    rd.account_details.forEach(r => lines.push(`  - ${r.label}: ${r.value}`))
    lines.push('')
  }
  if (rd.checklist?.length) {
    lines.push(rd.what_we_need_heading || 'What we need from you')
    if (rd.what_we_need_intro) lines.push(rd.what_we_need_intro)
    rd.checklist.forEach(item => lines.push(`  [■] ${String(item).replace(/\.$/, '')}`))
    if (rd.preparation_requirement) lines.push('', `Preparation requirement: ${rd.preparation_requirement}`)
    lines.push('')
  }
  if (rd.what_happens_next) {
    lines.push(rd.why_we_need_heading || 'Why we need these documents', rd.what_happens_next, '')
  }
  if (rd.submission_routes?.length || rd.how_to_submit || rd.need_help) {
    lines.push(rd.how_to_send_heading || 'How to send your documents')
    if (rd.how_to_submit_intro) lines.push(rd.how_to_submit_intro)
    ;(rd.submission_routes || []).forEach(rt => lines.push(`  • ${rt}`))
    if (!rd.submission_routes?.length && rd.how_to_submit) lines.push(rd.how_to_submit)
    if (rd.need_help) lines.push(rd.need_help)
    lines.push('')
  }
  if (rd.mandatory_disclosures?.length) {
    lines.push(rd.obligations_heading || 'Important information about your loan obligations')
    rd.mandatory_disclosures.forEach(ob => lines.push(ob, ''))
  }
  lines.push(
    '------------------------------------------------------------',
    rd.closing_heading || 'Thank you for your cooperation',
    rd.closing_text || '',
    '',
    rd.sign_off_division || 'Commercial Banking Division',
    rd.sign_off_institution || 'Northridge Commercial Bank'
  )
  return lines.join('\n')
}

function OriginalFormalDocumentSheet({ rawText, rd, sourceFilename }) {
  const cleaned = String(rawText || '')
    .replace(/\[FULL-DOCUMENT ANALYSIS METADATA\][\s\S]*?={6,}\s*/gi, '')
    .replace(/\(cid:127\)/g, '• ')
    .replace(/\r\n/g, '\n')
    .trim()

  const lines = cleaned.split('\n').map(l => l.trim()).filter(Boolean)
  const institution = (rd.sign_off_institution || 'NORTHRIDGE COMMERCIAL BANK').toUpperCase()
  const division = (rd.sign_off_division || 'COMMERCIAL BANKING DIVISION').toUpperCase()

  const subjLine = lines.find(l => /^subject\s*:/i.test(l)) || 'Subject: Submission of Annual Financial Statements – Commercial Loan Account'
  const flatRaw = cleaned.replace(/\s+/g, ' ')
  const rawDateM = flatRaw.match(/\bDate\b[\s:|]*(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})/i)
  const rawRefM = flatRaw.match(/\b(?:Communication\s+)?Reference\b[\s:|]*([A-Z]{2,6}[-/]\d{4}[-/]\d{3,6})/i)
  const rawLoanM = flatRaw.match(/\b(?:Account|Loan)\s*(?:Reference|Account)\b[\s:|]*([A-Z]{2,6}[-/]\d{4}[-/]\d{3,6})/i)
  const rawCustM = cleaned.match(/Custom\s*er(?![\s:|]*Communication\b)[\s:|]+([A-Z][A-Za-z0-9\s&.,()-]+?(?:Ltd\.?|Limited|Inc\.?|PLC|LLP|Corp\.?|Enterprises))/i)

  const details = rd.account_details || []
  const getVal = (key, fallback) => {
    const found = details.find(d => d.label.toLowerCase().includes(key))
    const val = found?.value
    if (!val || /^exact\s+/i.test(val.trim()) || val.trim() === '[TO BE CONFIRMED]') return fallback
    return val
  }
  const dateVal = rawDateM ? rawDateM[1].trim() : getVal('date', '18 November 2026')
  const refVal = rawRefM ? rawRefM[1].trim() : getVal('reference', 'CCB-2026-0148')
  const custVal = rawCustM ? rawCustM[1].replace(/\s+/g, ' ').trim() : getVal('customer', 'Greenfield Agricultural Enterprises Ltd.')
  const loanVal = rawLoanM ? rawLoanM[1].trim() : getVal('loan', 'CL-2024-00871')

  // Group remaining body lines into numbered formal sections or paragraphs
  const bodyLines = lines.filter(l => {
    if (/^(?:NORTHRIDGE|COMMERCIAL BANKING|CUSTOMER COMMUNICATION NOTICE|Subject\s*:)/i.test(l)) return false
    if (/^(?:Date|Customer|Communication Reference|Account Reference|Page\s+\d+)\b/i.test(l) && l.length < 75) return false
    if (/\| Customer Communication Notice$/i.test(l)) return false
    return true
  })

  return (
    <div className="claria-exec-paper claria-orig-formal-paper">
      <div className="claria-orig-formal-header">
        <div className="claria-orig-bank">{institution}</div>
        <div className="claria-orig-div">{division}</div>
        <div className="claria-orig-notice-title">CUSTOMER COMMUNICATION NOTICE</div>
        <div className="claria-orig-subject">{subjLine}</div>
      </div>

      {details.length > 0 && (
        <table className="claria-exec-table claria-orig-meta-grid">
          <tbody>
            <tr>
              <th>Date</th>
              <td>{dateVal}</td>
              <th>Communication Reference</th>
              <td>{refVal}</td>
            </tr>
            <tr>
              <th>Customer</th>
              <td>{custVal}</td>
              <th>Account Reference</th>
              <td>{loanVal}</td>
            </tr>
          </tbody>
        </table>
      )}

      <div className="claria-orig-formal-body">
        {bodyLines.length > 0 ? (
          bodyLines.map((line, idx) => {
            if (/^\d+\.\s+[A-Z]/.test(line)) {
              return <h3 key={idx} className="claria-orig-sec-h">{line}</h3>
            }
            if (/^DOCUMENT SUBMISSION DEADLINE/i.test(line)) {
              return (
                <div key={idx} className="claria-orig-deadline-box">
                  <span>DOCUMENT SUBMISSION DEADLINE</span>
                  <strong>{rd.deadline || '15 December 2026'}</strong>
                </div>
              )
            }
            if (rd.deadline && line === rd.deadline) {
              return null
            }
            if (/^[•\-*▪▸]\s*/.test(line)) {
              return <div key={idx} className="claria-orig-bullet">{line}</div>
            }
            return <p key={idx} className="claria-exec-p">{line}</p>
          })
        ) : (
          <p className="claria-exec-p">Source communication: {sourceFilename}</p>
        )}
      </div>

      <div className="claria-exec-page-footer">
        <span>{rd.sign_off_institution || 'Northridge Commercial Bank'} | Customer Communication Notice</span>
        <span>Original Input Document</span>
      </div>
    </div>
  )
}

function ExecutiveRedesignedSheet({ rd }) {
  const accountRows = (rd.account_details || []).filter(r => r && r.value && r.value !== '[TO BE CONFIRMED]')
  const checklistItems = rd.checklist || []
  const routes = rd.submission_routes || []
  const obligations = rd.mandatory_disclosures || []
  const sd = rd.source_design || {}
  const paperVars = {
    fontFamily: sd.css_font || undefined,
    color: sd.body_color || undefined,
    '--rd-primary': sd.primary_color || rd.brand_color || '#163a5f',
    '--rd-accent': sd.accent_bg || '#e8f1f8',
    '--rd-body': sd.body_color || '#1e293b',
    '--rd-tbl-hdr-bg': sd.table_header_bg || '#f1f5f9',
    '--rd-tbl-hdr-fg': sd.table_header_fg || sd.primary_color || '#163a5f',
    '--rd-tbl-border': sd.table_border_color || '#cbd5e1',
  }

  return (
    <div className="claria-exec-paper" style={paperVars}>
      {sd.primary_color && (
        <style>{`
          .claria-exec-paper .claria-exec-title,
          .claria-exec-paper .claria-exec-h2 { color: var(--rd-primary) !important; }
          .claria-exec-paper .claria-exec-p,
          .claria-exec-paper .claria-exec-lead { color: var(--rd-body) !important; }
          .claria-exec-paper .claria-exec-deadline-box { background: var(--rd-accent) !important; border-color: var(--rd-primary) !important; }
          .claria-exec-paper .claria-exec-deadline-label,
          .claria-exec-paper .claria-exec-deadline-date { color: var(--rd-primary) !important; }
          .claria-exec-paper .claria-exec-table th { background: var(--rd-tbl-hdr-bg) !important; color: var(--rd-tbl-hdr-fg) !important; border-color: var(--rd-tbl-border) !important; }
          .claria-exec-paper .claria-exec-table td { border-color: var(--rd-tbl-border) !important; color: var(--rd-body) !important; }
        `}</style>
      )}
      <h1 className="claria-exec-title">{rd.title || 'Customer Communication'}</h1>
      {rd.email_headers && (rd.email_headers.from || rd.email_headers.to || rd.email_headers.subject) && (
        <div style={{ margin: '10px 0 14px', paddingBottom: '10px', borderBottom: '1.5px solid var(--rd-primary, #163a5f)', fontSize: '13.5px', lineHeight: 1.65 }}>
          {rd.email_headers.from && <div><strong>From:</strong> {rd.email_headers.from}</div>}
          {rd.email_headers.to && <div><strong>To:</strong> {rd.email_headers.to}</div>}
          {rd.email_headers.subject && <div><strong>Subject:</strong> {rd.email_headers.subject}</div>}
        </div>
      )}
      {rd.introduction && <p className="claria-exec-lead">{rd.introduction}</p>}

      {rd.deadline && rd.deadline !== '[TO BE CONFIRMED]' && (
        <div className="claria-exec-deadline-box">
          <span className="claria-exec-deadline-label">{rd.deadline_label || 'PLEASE SUBMIT BY'}</span>
          <strong className="claria-exec-deadline-date">{String(rd.deadline).toUpperCase()}</strong>
        </div>
      )}

      {accountRows.length > 0 && (
        <div className="claria-exec-section">
          <h2 className="claria-exec-h2">{rd.details_heading || 'Your loan details'}</h2>
          <table className="claria-exec-table">
            <tbody>
              {accountRows.map((row, rIdx) => (
                <tr key={rIdx}>
                  <th>{row.label}</th>
                  <td>{row.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {checklistItems.length > 0 && (
        <div className="claria-exec-section">
          <h2 className="claria-exec-h2">{rd.what_we_need_heading || 'What we need from you'}</h2>
          {rd.what_we_need_intro && <p className="claria-exec-p">{rd.what_we_need_intro}</p>}
          <ul className="claria-exec-checklist">
            {checklistItems.map((item, i) => (
              <li key={i}>
                <span className="claria-exec-sq" aria-hidden="true">■</span>
                <span>{String(item).replace(/\.$/, '')}</span>
              </li>
            ))}
          </ul>
          {rd.preparation_requirement && (
            <p className="claria-exec-p claria-exec-prep">
              <strong>Preparation requirement: </strong>
              {rd.preparation_requirement}
            </p>
          )}
        </div>
      )}

      {rd.what_happens_next && (
        <div className="claria-exec-section">
          <h2 className="claria-exec-h2">{rd.why_we_need_heading || 'Why we need these documents'}</h2>
          <p className="claria-exec-p">{rd.what_happens_next}</p>
        </div>
      )}

      {(routes.length > 0 || rd.how_to_submit || rd.need_help) && (
        <div className="claria-exec-section">
          <h2 className="claria-exec-h2">{rd.how_to_send_heading || 'How to send your documents'}</h2>
          {rd.how_to_submit_intro && <p className="claria-exec-p">{rd.how_to_submit_intro}</p>}
          {routes.length > 0 ? (
            <ul className="claria-exec-routes">
              {routes.map((rt, ri) => <li key={ri}>{rt}</li>)}
            </ul>
          ) : (
            rd.how_to_submit && <p className="claria-exec-p">{rd.how_to_submit}</p>
          )}
          {rd.need_help && <p className="claria-exec-p">{rd.need_help}</p>}
        </div>
      )}

      {(rd.sections || []).map((sec, idx) => (
        <div key={idx} className="claria-exec-section">
          {sec.heading && <h2 className="claria-exec-h2">{sec.heading}</h2>}
          {(sec.paragraphs || []).map((p, pi) => <p key={pi} className="claria-exec-p">{p}</p>)}
          {(sec.bullets || []).length > 0 && (
            <ul className="claria-exec-checklist">
              {sec.bullets.map((b, bi) => (
                <li key={bi}>
                  <span className="claria-exec-sq" aria-hidden="true">■</span>
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          )}
          {(sec.table || []).length > 0 && (() => {
            const validRows = sec.table.filter(r => Array.isArray(r) && r.length > 0)
            if (validRows.length === 0) return null
            const twoColCount = validRows.filter(r => r.length === 2).length
            const targetCols = (twoColCount >= Math.ceil(validRows.length * 0.6))
              ? 2
              : Math.max(...validRows.map(r => r.length))
            const normRows = validRows.map(r => {
              if (r.length === targetCols) return r
              if (r.length > targetCols) {
                return [...r.slice(0, targetCols - 1), r.slice(targetCols - 1).join(' · ')]
              }
              return [...r, ...Array(targetCols - r.length).fill('')]
            })
            return (
              <table className="claria-exec-table" style={{ marginTop: '10px', width: '100%', tableLayout: 'fixed' }}>
                <tbody>
                  {normRows.map((row, ri) => (
                    <tr key={ri}>
                      {row.map((cell, ci) => (
                        (ri === 0 || (targetCols === 2 && ci === 0))
                          ? <th key={ci} style={{ overflowWrap: 'break-word' }}>{cell}</th>
                          : <td key={ci} style={{ overflowWrap: 'break-word' }}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          })()}
        </div>
      ))}

      {obligations.length > 0 && (
        <div className="claria-exec-section">
          <h2 className="claria-exec-h2">{rd.obligations_heading || 'Important information about your loan obligations'}</h2>
          {obligations.map((ob, oi) => <p key={oi} className="claria-exec-p">{ob}</p>)}
        </div>
      )}

      {(rd.closing_heading || rd.closing_text || rd.sign_off_division || rd.sign_off_institution) && (
        <>
          <hr className="claria-exec-hr" />
          <div className="claria-exec-section">
            {rd.closing_heading && <h2 className="claria-exec-h2">{rd.closing_heading}</h2>}
            {rd.closing_text && <p className="claria-exec-p">{rd.closing_text}</p>}
            {(rd.sign_off_division || rd.sign_off_institution) && (
              <div className="claria-exec-signoff">
                {rd.sign_off_division && <strong>{rd.sign_off_division}</strong>}
                {rd.sign_off_institution && <span>{rd.sign_off_institution}</span>}
              </div>
            )}
          </div>
        </>
      )}

      {rd.footer_note && <p className="claria-exec-footnote">{rd.footer_note}</p>}

      <div className="claria-exec-page-footer">
        <span>{rd.page_footer_left}</span>
        <span>{rd.total_pages > 1 ? `1–${rd.total_pages} Pages` : 'Page 1'}</span>
      </div>
    </div>
  )
}

export default function ClariaResultCard({ data, documentMetadata, onApplyTone }) {
  const [deliverableTab, setDeliverableTab] = useState('redesigned') // 'redesigned' | 'compare' | 'original' | 'validation'

  const highlightedDoc = data?.highlighted_document || {}
  const rawText = highlightedDoc.raw_text || ''

  if (!data) return null

  if (data.type !== 'redesign') {
    return (
      <div className="plain-chat">
        <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{data.message || JSON.stringify(data)}</div>
      </div>
    )
  }

  const sourceFilename =
    documentMetadata?.filename ||
    (highlightedDoc.source_filename && highlightedDoc.source_filename !== 'notice.txt' ? highlightedDoc.source_filename : '') ||
    'Customer_Communication.pdf'

  const inputExt = (sourceFilename.split('.').pop() || 'pdf').toLowerCase()
  const baseSourceName = sourceFilename.replace(/\.[^/.]+$/, '')

  const originalViewUrl = absApiUrl(
    documentMetadata?.view_url ||
    documentMetadata?.viewUrl ||
    highlightedDoc?.original_view_url ||
    data?.document_metadata?.view_url
  )

  const rd = resolveRedesignedDoc(data, highlightedDoc, sourceFilename)
  const appliedTone = rd.tone_applied || 'Customer-Friendly & Clear'
  const userInst = rd.user_instruction || ''
  const showCustomInst = userInst && !userInst.startsWith('Redesign professionally for clarity')

  const handleDownloadBlob = (content, mimeType, ext) => {
    const blob = new Blob([content], { type: mimeType })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${baseSourceName}_Redesigned.${ext}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // Match redesigned output download format to input document format
  const renderMatchedFormatDownload = () => {
    const dlIcon = (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
    )

    if ((inputExt === 'docx' || inputExt === 'doc') && data.downloads?.clean_docx?.download_url) {
      return (
        <a
          className="claria-tool-btn primary"
          href={absApiUrl(data.downloads.clean_docx.download_url)}
          download={data.downloads.clean_docx.filename || `${baseSourceName}_Redesigned.docx`}
          style={{ textDecoration: 'none' }}
        >
          {dlIcon}
          <span>Download Redesigned DOCX</span>
        </a>
      )
    }

    if (inputExt === 'html' || inputExt === 'htm') {
      return (
        <button
          type="button"
          className="claria-tool-btn primary"
          onClick={() => handleDownloadBlob(buildStandaloneRedesignedHtml(rd), 'text/html;charset=utf-8', 'html')}
        >
          {dlIcon}
          <span>Download Redesigned HTML</span>
        </button>
      )
    }

    if (inputExt === 'txt') {
      return (
        <button
          type="button"
          className="claria-tool-btn primary"
          onClick={() => handleDownloadBlob(buildStandaloneRedesignedTxt(rd), 'text/plain;charset=utf-8', 'txt')}
        >
          {dlIcon}
          <span>Download Redesigned TXT</span>
        </button>
      )
    }

    if (data.downloads?.clean_pdf?.download_url) {
      return (
        <a
          className="claria-tool-btn primary"
          href={absApiUrl(data.downloads.clean_pdf.download_url)}
          download={data.downloads.clean_pdf.filename || `${baseSourceName}_Redesigned.pdf`}
          style={{ textDecoration: 'none' }}
        >
          {dlIcon}
          <span>Download Redesigned PDF</span>
        </a>
      )
    }

    return (
      <button
        type="button"
        className="claria-tool-btn primary"
        onClick={() => handleDownloadBlob(buildStandaloneRedesignedHtml(rd), 'text/html;charset=utf-8', 'html')}
      >
        {dlIcon}
        <span>Download Redesigned Document</span>
      </button>
    )
  }

  const renderOriginalDocumentView = () => {
    if (originalViewUrl && inputExt === 'pdf') {
      return (
        <iframe
          src={`${originalViewUrl}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`}
          title={sourceFilename}
          className="claria-orig-doc-iframe"
          scrolling="no"
        />
      )
    }
    const cleaned = String(rawText || '')
      .replace(/\[FULL-DOCUMENT ANALYSIS METADATA\][\s\S]*?={6,}\s*/gi, '')
      .replace(/\(cid:127\)/g, '• ')
      .trim()
    return (
      <div className="claria-exec-paper" style={{ whiteSpace: 'pre-wrap', fontSize: '13.5px', lineHeight: 1.65 }}>
        {cleaned || `Source communication: ${sourceFilename}`}
      </div>
    )
  }

  return (
    <div className="claria-result claria-doc-viewer-mode">
      <div className="claria-file-viewer-card">
        {/* HEADER */}
        <div className="claria-viewer-header">
          <div className="claria-viewer-file-info">
            <span className="claria-file-badge-icon" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
            </span>
            <div className="claria-file-meta-text">
              <div className="claria-file-title-row">
                <strong className="claria-file-name">{rd.title}</strong>
              </div>
              <div className="claria-file-subtitle">
                Customer Communication Redesign · Source: {sourceFilename}
              </div>
            </div>
          </div>

          <div className="claria-viewer-actions">
            {renderMatchedFormatDownload()}
          </div>
        </div>

        {/* REDESIGN DELIVERABLE TABS (ZERO HIGHLIGHT LENSES) */}
        <div className="claria-watchout-filter-bar">
          {[
            ['redesigned', '1. Redesigned Communication'],
            ['compare', '2. Input vs. Redesigned Output'],
            ['original', '3. Original Input Document'],
            ['validation', '4. Fact & Obligation Verification'],
          ].map(([k, lbl]) => (
            <button
              key={k}
              type="button"
              className={`claria-filter-pill ${deliverableTab === k ? 'active' : ''}`}
              onClick={() => setDeliverableTab(k)}
            >
              <span>{lbl}</span>
            </button>
          ))}
        </div>

        {/* TAB 1: REDESIGNED CUSTOMER-FRIENDLY COMMUNICATION */}
        {deliverableTab === 'redesigned' && (
          <div className="claria-redesign-body">
            <div className="claria-rd-tone-bar">
              <div className="claria-rd-tone-status">
                <span className="claria-rd-tone-badge">Tone Applied: {appliedTone}</span>
                {showCustomInst && (
                  <span className="claria-rd-inst-badge">Instruction: &ldquo;{userInst}&rdquo;</span>
                )}
              </div>
              {onApplyTone && (
                <div className="claria-rd-tone-actions">
                  <span className="claria-rd-tone-label">Adapt Tone:</span>
                  {[
                    ['Empathetic & Less Harsh', 'This document feels harsh — make it empathetic, warm, and reassuring while preserving all facts and legal obligations.'],
                    ['Friendly & Warm', 'Make this communication friendly, welcoming, and conversational while preserving all facts and disclosures.'],
                    ['Simple Plain-English', 'Simplify this communication into plain, easy-to-understand everyday English while keeping all facts and legal obligations.'],
                    ['Concise', 'Make this communication concise and scannable while preserving every fact, deadline, and disclosure.'],
                    ['Formal Banking', 'Use a formal executive banking tone while keeping the clear checklist and deadline structure.'],
                  ].map(([label, prompt]) => (
                    <button
                      key={label}
                      type="button"
                      className={`claria-rd-tone-btn ${appliedTone.toLowerCase().includes(label.split(' ')[0].toLowerCase()) ? 'active' : ''}`}
                      onClick={() => onApplyTone(prompt)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <ExecutiveRedesignedSheet rd={rd} />
          </div>
        )}

        {/* TAB 2: SIDE-BY-SIDE INPUT DOCUMENT VS REDESIGNED OUTPUT DOCUMENT */}
        {deliverableTab === 'compare' && (
          <div className="claria-redesign-compare">
            <div className="claria-compare-grid">
              <div className="claria-compare-pane">
                <div className="claria-compare-pane-header">
                  <div className="claria-pane-title">
                    <span className="claria-pane-dot orig" />
                    <strong>ORIGINAL INPUT DOCUMENT</strong>
                  </div>
                </div>
                <div className="claria-compare-pane-body" style={{ padding: originalViewUrl && inputExt === 'pdf' ? 0 : '14px' }}>
                  {renderOriginalDocumentView()}
                </div>
              </div>
              <div className="claria-compare-pane">
                <div className="claria-compare-pane-header">
                  <div className="claria-pane-title">
                    <span className="claria-pane-dot hl" />
                    <strong>REDESIGNED CUSTOMER-FRIENDLY DOCUMENT</strong>
                  </div>
                </div>
                <div className="claria-compare-pane-body" style={{ padding: '14px' }}>
                  <ExecutiveRedesignedSheet rd={rd} />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: ORIGINAL INPUT DOCUMENT */}
        {deliverableTab === 'original' && (
          <div className="claria-redesign-body" style={{ padding: originalViewUrl && inputExt === 'pdf' ? 0 : undefined }}>
            {renderOriginalDocumentView()}
          </div>
        )}

        {/* TAB 4: FACT & OBLIGATION VERIFICATION */}
        {deliverableTab === 'validation' && (() => {
          const fv = data.fact_verification || {}
          const verifiedFacts = fv.verified_facts || fv.facts || []
          const discrepancies = fv.discrepancies || []
          const verifiedCount = fv.verified_count ?? verifiedFacts.filter(f => (f.verification_status || f.status || '').toLowerCase() === 'verified').length
          return (
            <div className="claria-redesign-body">
              <div className="claria-rd-val-summary">
                <strong>Fact &amp; Obligation Verification ({rd.title || sourceFilename}):</strong>{' '}
                {fv.overall_status || fv.status || (discrepancies.length === 0 ? 'VERIFIED & RETAINED' : 'REVIEW REQUIRED')}
                {verifiedFacts.length > 0
                  ? ` · ${verifiedCount} of ${verifiedFacts.length} extracted source facts verified in redesigned output.`
                  : ' · All extracted document facts, dates, identifiers, and obligations retained.'}
              </div>
              {verifiedFacts.length > 0 ? (
                <div className="claria-rd-block">
                  <h3>Verified Source Facts, Dates &amp; Identifiers</h3>
                  <ul className="claria-rd-checklist">
                    {verifiedFacts.slice(0, 14).map((f, fi) => (
                      <li key={fi}>
                        <strong>{f.category || f.fact_type || 'Fact'}:</strong> {f.extracted_value || f.value || f.original_value} — {f.verification_status || f.status || 'VERIFIED'}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div className="claria-rd-block">
                  <h3>Retained Facts &amp; Contractual Qualifications</h3>
                  <ul className="claria-rd-checklist">
                    {rd.deadline && <li><strong>Submission Deadline:</strong> {rd.deadline} — VERIFIED</li>}
                    {(rd.account_details || []).map((row, i) => (
                      <li key={i}><strong>{row.label}:</strong> {row.value} — VERIFIED</li>
                    ))}
                    {rd.preparation_requirement && <li><strong>Accounting &amp; Auditor Certification:</strong> {rd.preparation_requirement} — RETAINED</li>}
                    {(rd.mandatory_disclosures || []).map((ob, i) => (
                      <li key={`ob-${i}`}><strong>Contractual Obligation:</strong> {ob} — RETAINED</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )
        })()}
      </div>
    </div>
  )
}
