import { useState, useRef, useMemo } from 'react'
import { absApiUrl } from '../services/api'

const CLARITY_LENSES = {
  all: {
    key: 'all',
    label: 'All Highlights',
    dot: '#38bdf8'
  },
  what_to_do: {
    key: 'what_to_do',
    label: 'What You Need To Do',
    dot: '#fde047'
  },
  core_message: {
    key: 'core_message',
    label: 'Key Message',
    dot: '#7dd3fc'
  },
  timeline_dates: {
    key: 'timeline_dates',
    label: 'Important Dates',
    dot: '#fdba74'
  },
  customer_impact: {
    key: 'customer_impact',
    label: 'Important Details',
    dot: '#6ee7b7'
  }
}

const LEGACY_CAT_MAP = {
  mandatory_action: 'what_to_do',
  critical_watchout: 'customer_impact',
  deadline_window: 'timeline_dates',
  financial_impact: 'customer_impact',
  key_clause: 'core_message'
}

const CAT_LABELS = {
  what_to_do: 'What You Need To Do',
  core_message: 'Key Message',
  timeline_dates: 'Important Dates',
  customer_impact: 'Important Details'
}

function renderFormattedSummary(text) {
  const raw = String(text || '').trim()
  if (!raw) return null

  // Split inline numbered points like "1. ... 2. ... 3. ..." into structured list items
  const numberedSplit = raw.split(/\s+(?=\d+\.\s+)/)
  if (numberedSplit.length >= 3) {
    const intro = numberedSplit[0].trim()
    const rawItems = numberedSplit.slice(1)
    const items = []
    let outro = ''

    rawItems.forEach((item, idx) => {
      const cleaned = item.replace(/^\d+\.\s*/, '').trim()
      if (idx === rawItems.length - 1) {
        const sumMatch = cleaned.match(/^(.*?\.)\s+(In summary,[\s\S]+)$/i)
        if (sumMatch) {
          items.push(sumMatch[1].trim())
          outro = sumMatch[2].trim()
          return
        }
      }
      items.push(cleaned)
    })

    return (
      <div className="claria-summary-formatted">
        {intro && <p className="claria-summary-intro">{intro}</p>}
        <ol className="claria-summary-list">
          {items.map((it, i) => (
            <li key={i}>{it}</li>
          ))}
        </ol>
        {outro && <p className="claria-summary-outro">{outro}</p>}
      </div>
    )
  }

  return (
    <div className="claria-summary-formatted">
      {raw.split(/\n+/).map((p, i) => (
        <p key={i} className="claria-summary-intro">{p.trim()}</p>
      ))}
    </div>
  )
}

function normalizeDocumentDom(rawHtml, isHighlighted) {
  if (!rawHtml || typeof window === 'undefined') {
    return { html: rawHtml || '', counts: { all: 0, what_to_do: 0, core_message: 0, timeline_dates: 0, customer_impact: 0 }, items: [] }
  }

  const cleanedStr = rawHtml
    .replace(/\(cid:127\)/g, '• ')
    .replace(/<span[^>]*class="[^"]*claria-inline-tag[^"]*"[^>]*>[\s\S]*?<\/span>/gi, '')

  const parser = new DOMParser()
  const doc = parser.parseFromString(`<div id="root">${cleanedStr}</div>`, 'text/html')
  const root = doc.getElementById('root')
  if (!root) {
    return { html: cleanedStr, counts: { all: 0, what_to_do: 0, core_message: 0, timeline_dates: 0, customer_impact: 0 }, items: [] }
  }

  // 1. Remove any internal metadata header lines ([FULL-DOCUMENT ANALYSIS METADATA] ... ====)
  const allLines = Array.from(root.querySelectorAll('.claria-doc-line'))
  let inMetaHeader = false
  for (const ln of allLines) {
    const txt = (ln.textContent || '').trim()
    if (txt.includes('[FULL-DOCUMENT ANALYSIS METADATA]')) {
      inMetaHeader = true
      ln.remove()
      continue
    }
    if (inMetaHeader) {
      ln.remove()
      if (txt.startsWith('====')) {
        inMetaHeader = false
      }
    }
  }

  // 2. Merge soft-wrapped PDF continuation lines so half-sentences (like "cannot understand." or "paragraphs.")
  // are rejoined onto the previous line before evaluating sentence highlights!
  const sheet = root.querySelector('.claria-doc-sheet') || root
  const remainingLines = Array.from(sheet.querySelectorAll('.claria-doc-line'))
  for (let i = 1; i < remainingLines.length; i++) {
    const curr = remainingLines[i]
    const prev = remainingLines[i - 1]
    if (!curr.parentNode || !prev.parentNode) continue
    if (curr.classList.contains('claria-blank-line') || prev.classList.contains('claria-blank-line')) continue
    if (curr.classList.contains('claria-line-heading') || curr.classList.contains('claria-line-table')) continue

    const currTxt = (curr.textContent || '').trim()
    const prevTxt = (prev.textContent || '').trim()
    if (!currTxt || !prevTxt) continue

    const startsNewBulletOrNum = /^(?:[\•\-\*\▪\▸]|\d+[\.\)]|[A-Z]\.\s|\([a-zA-Z0-9]+\)|\[Page\b)/i.test(currTxt)
    const prevEndsSentence = /[\.\!\?\:][\"\'\)\]]*$/.test(prevTxt)

    if (!startsNewBulletOrNum && (!prevEndsSentence || /^[a-z]/.test(currTxt) || currTxt.split(/\s+/).length <= 3)) {
      // Merge curr into prev
      prev.innerHTML = prev.innerHTML.trimEnd() + ' ' + curr.innerHTML.trimStart()
      curr.remove()
      remainingLines[i] = prev
    }
  }

  // 3. Clean up <mark> elements: merge adjacent marks in the same sentence, unwrap single-word/short marks (< 5 words),
  // and normalize category classes
  const counts = { all: 0, what_to_do: 0, core_message: 0, timeline_dates: 0, customer_impact: 0 }
  const items = []

  if (isHighlighted) {
    // Merge adjacent <mark> nodes separated only by whitespace within the same line
    for (const ln of Array.from(sheet.querySelectorAll('.claria-doc-line'))) {
      let merged = true
      while (merged) {
        merged = false
        const marks = Array.from(ln.querySelectorAll('mark'))
        for (let i = 0; i < marks.length - 1; i++) {
          const m1 = marks[i]
          const m2 = marks[i + 1]
          if (m1.nextSibling === m2 || (m1.nextSibling && m1.nextSibling.nodeType === 3 && !m1.nextSibling.textContent.trim() && m1.nextSibling.nextSibling === m2)) {
            const m1Txt = (m1.textContent || '').trim()
            if (!/[\.\!\?]$/.test(m1Txt)) {
              const space = (m1.nextSibling && m1.nextSibling.nodeType === 3) ? m1.nextSibling.textContent : ' '
              if (m1.nextSibling && m1.nextSibling.nodeType === 3) m1.nextSibling.remove()
              m1.textContent = m1Txt + space + (m2.textContent || '').trim()
              m2.remove()
              merged = true
              break
            }
          }
        }
      }
    }

    const inferSmartCategory = (txt, rawCat) => {
      if (CLARITY_LENSES[rawCat]) return rawCat
      const t = txt.toLowerCase()
      if (/\b(?:must|need to|required to|please|submit|confirm|verify|steps? to|action required|always|keep each|maintain a|never rely)\b/.test(t)) {
        return 'what_to_do'
      }
      if (/\b(?:november|december|january|february|march|april|may|june|july|august|september|october|deadline|due by|within \d+|under \d+ seconds|\$\d+|0\.1|100%)\b/.test(t)) {
        return 'timeline_dates'
      }
      if (/\b(?:what is this|core mission|master study guide|explains how|analyzes it|plain-language|plain-english|blueprint|overview)\b/.test(t)) {
        return 'core_message'
      }
      if (/\b(?:cannot understand|hidden inside|flood call centers|consequence|penalty|restrictions|passed|prevents|ensures|auditability|no action required)\b/.test(t)) {
        return 'customer_impact'
      }
      return LEGACY_CAT_MAP[rawCat] || 'core_message'
    }

    const candidateMarks = []
    const finalMarks = Array.from(root.querySelectorAll('mark'))
    finalMarks.forEach((mark) => {
      mark.querySelectorAll('.claria-inline-tag').forEach((el) => el.remove())
      const fullTxt = (mark.textContent || '').replace(/\s+/g, ' ').trim()
      const wordCount = fullTxt ? fullTxt.split(/\s+/).length : 0

      // Unwrap any single-word or short fragment (< 5 words)
      if (wordCount < 5 || mark.classList.contains('claria-hl-inline')) {
        const textNode = doc.createTextNode(mark.textContent || '')
        mark.replaceWith(textNode)
        return
      }

      // If mark starts with a bullet/title prefix before a colon (e.g. "• Intimidating Legalese: Filled with..."),
      // move the prefix outside the <mark> so the title stays clean white text and only the takeaway clause is highlighted!
      const rawMarkText = mark.textContent || ''
      const prefixMatch = rawMarkText.match(/^((?:[\•\-\*\▪\▸]|\d+[\.\)])?\s*[A-Za-z0-9\s\-\/\'\"\(\)`]{2,38}:\s+)([\s\S]{20,})$/)
      if (prefixMatch && mark.parentNode) {
        const prefixNode = doc.createTextNode(prefixMatch[1])
        mark.parentNode.insertBefore(prefixNode, mark)
        mark.textContent = prefixMatch[2]
      }

      const txt = (mark.textContent || '').replace(/\s+/g, ' ').trim()
      const rawCat = mark.getAttribute('data-category') || ''
      const normCat = inferSmartCategory(txt, rawCat)
      candidateMarks.push({ mark, normCat, txt })
    })

    // Keep all important highlights across the full document without capping
    const keptMarks = candidateMarks

    keptMarks.forEach(({ mark, normCat, txt }) => {
      const cleanLabel = CAT_LABELS[normCat] || 'Key Sentence'
      let note = mark.getAttribute('data-note') || ''
      note = note.replace(/^Watchout warning:\s*/i, '').replace(/^Critical watchout clause:\s*/i, '')

      mark.className = `claria-hl-sentence claria-cat-${normCat}`
      mark.setAttribute('data-category', normCat)
      mark.setAttribute('data-label', cleanLabel)
      if (note) mark.setAttribute('data-note', note)

      counts[normCat] = (counts[normCat] || 0) + 1
      counts.all += 1
      items.push({
        category: normCat,
        label: cleanLabel,
        note: note || 'Highlighted key takeaway in this communication.',
        verbatim_text: txt
      })
    })

    // Normalize paragraph left-border classes
    for (const ln of Array.from(sheet.querySelectorAll('.claria-doc-line'))) {
      ln.classList.remove(
        'claria-para-watchout-critical',
        'claria-para-watchout-action',
        'claria-para-watchout-deadline',
        'claria-para-watchout-financial',
        'claria-para-what_to_do',
        'claria-para-core_message',
        'claria-para-timeline_dates',
        'claria-para-customer_impact'
      )
      const firstMark = ln.querySelector('mark[data-category]')
      if (firstMark) {
        const c = firstMark.getAttribute('data-category')
        if (c) ln.classList.add(`claria-para-${c}`)
      }
    }
  }

  return { html: root.innerHTML, counts, items }
}

function buildInteractiveStandaloneHtml(title, subtitle, originalHtml, highlightedHtml, counts) {
  const esc = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${esc(title)}</title>
  <style>
    :root { --bg: #020c16; --panel: #051a2c; --sheet: #041628; --text: #f0f7ff; --muted: #849bb4; --border: rgba(7, 140, 255, 0.25); }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 18px; background: var(--bg); color: var(--text); font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.7; font-size: 14px; }
    .wrap { max-width: 1200px; margin: 0 auto; }
    .topBar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 18px; background: var(--panel); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 12px; }
    .titleGrp { display: flex; align-items: center; gap: 12px; }
    .docIcon { width: 36px; height: 36px; border-radius: 9px; background: rgba(7, 140, 255, 0.14); border: 1px solid rgba(7, 140, 255, 0.35); display: grid; place-items: center; color: #38bdf8; flex-shrink: 0; }
    .titleGrp h1 { font-size: 15.5px; margin: 0 0 2px; color: #fff; }
    .sub { font-size: 12.5px; color: var(--muted); margin: 0; }
    .btnGrp { display: flex; gap: 8px; }
    .btn { padding: 7px 13px; border-radius: 8px; border: 1px solid var(--border); background: rgba(7, 140, 255, 0.12); color: #fff; font-weight: 600; font-size: 12px; cursor: pointer; }
    .btn.active { background: #078cff; border-color: #38bdf8; }
    .legendBar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 16px; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 12px; }
    .legPill { padding: 5px 11px; border-radius: 999px; font-weight: 600; font-size: 11.5px; border: 1px solid rgba(255, 255, 255, 0.14); background: rgba(5, 26, 44, 0.8); color: #cbd5e1; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
    .legPill.active { background: rgba(7, 140, 255, 0.24); border-color: #38bdf8; color: #fff; }
    .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
    .compareGrid { display: grid; grid-template-columns: 1fr; gap: 14px; }
    .compareGrid.split { grid-template-columns: 1fr 1fr; }
    .pane { background: var(--sheet); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
    .paneHead { padding: 10px 16px; background: rgba(2, 12, 22, 0.7); border-bottom: 1px solid var(--border); font-weight: 700; font-size: 12px; display: flex; justify-content: space-between; }
    .claria-doc-sheet { padding: 20px; font-size: 14px; line-height: 1.8; white-space: pre-wrap; word-break: break-word; }
    .claria-doc-line { min-height: 1.4em; padding: 3px 8px; border-radius: 5px; }
    .claria-line-heading { font-weight: 800; color: #ffffff; font-size: 15px; margin-top: 10px; margin-bottom: 4px; }
    .claria-para-what_to_do { border-left: 3px solid #facc15; padding-left: 12px; margin: 4px 0; }
    .claria-para-core_message { border-left: 3px solid #38bdf8; padding-left: 12px; margin: 4px 0; }
    .claria-para-timeline_dates { border-left: 3px solid #fb923c; padding-left: 12px; margin: 4px 0; }
    .claria-para-customer_impact { border-left: 3px solid #34d399; padding-left: 12px; margin: 4px 0; }
    mark, .claria-hl-sentence { padding: 2px 6px; border-radius: 4px; background: #fde047; color: #050b14 !important; font-weight: 600; }
    .claria-cat-what_to_do { background: #fde047 !important; color: #050b14 !important; }
    .claria-cat-core_message { background: #7dd3fc !important; color: #050b14 !important; }
    .claria-cat-timeline_dates { background: #fdba74 !important; color: #050b14 !important; }
    .claria-cat-customer_impact { background: #6ee7b7 !important; color: #050b14 !important; }
    body.filter-what_to_do mark:not(.claria-cat-what_to_do),
    body.filter-core_message mark:not(.claria-cat-core_message),
    body.filter-timeline_dates mark:not(.claria-cat-timeline_dates),
    body.filter-customer_impact mark:not(.claria-cat-customer_impact) {
      background: transparent !important; color: #e2e8f0 !important; font-weight: 400 !important; padding: 0 !important;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topBar">
      <div class="titleGrp">
        <div class="docIcon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        </div>
        <div>
          <h1>${esc(title)}</h1>
          <p class="sub">${esc(subtitle)}</p>
        </div>
      </div>
      <div class="btnGrp">
        <button class="btn active" id="btnSingle" onclick="setMode('single')">Highlighted Document</button>
        <button class="btn" id="btnCompare" onclick="setMode('compare')">Compare Input &amp; Output</button>
      </div>
    </div>
    <div class="legendBar">
      <button class="legPill active" onclick="setFilter('all', this)"><span class="dot" style="background:#38bdf8"></span>All Highlights (${counts.all || 0})</button>
      <button class="legPill" onclick="setFilter('what_to_do', this)"><span class="dot" style="background:#fde047"></span>What You Need To Do (${counts.what_to_do || 0})</button>
      <button class="legPill" onclick="setFilter('core_message', this)"><span class="dot" style="background:#7dd3fc"></span>Key Message (${counts.core_message || 0})</button>
      <button class="legPill" onclick="setFilter('timeline_dates', this)"><span class="dot" style="background:#fdba74"></span>Important Dates (${counts.timeline_dates || 0})</button>
      <button class="legPill" onclick="setFilter('customer_impact', this)"><span class="dot" style="background:#6ee7b7"></span>Important Details (${counts.customer_impact || 0})</button>
    </div>
    <div class="compareGrid" id="gridWrap">
      <div class="pane" id="origPane" style="display:none">
        <div class="paneHead"><span>Uploaded File (Input)</span><span>Original</span></div>
        ${originalHtml}
      </div>
      <div class="pane">
        <div class="paneHead"><span>Highlighted Output</span><span>Clarity View</span></div>
        ${highlightedHtml}
      </div>
    </div>
  </div>
  <script>
    function setMode(mode) {
      var grid = document.getElementById('gridWrap');
      var orig = document.getElementById('origPane');
      var bSingle = document.getElementById('btnSingle');
      var bComp = document.getElementById('btnCompare');
      if (mode === 'compare') {
        grid.classList.add('split'); orig.style.display = 'block';
        bComp.classList.add('active'); bSingle.classList.remove('active');
      } else {
        grid.classList.remove('split'); orig.style.display = 'none';
        bSingle.classList.add('active'); bComp.classList.remove('active');
      }
    }
    function setFilter(cat, btn) {
      document.body.className = cat === 'all' ? '' : 'filter-' + cat;
      var pills = document.querySelectorAll('.legPill');
      for (var i = 0; i < pills.length; i++) pills[i].classList.remove('active');
      if (btn) btn.classList.add('active');
    }
  </script>
</body>
</html>`
}

export default function ClariaResultCard({ data, documentMetadata, onOpenDocument, onApplyTone }) {
  const [deliverableTab, setDeliverableTab] = useState('redesigned') // 'redesigned' | 'original' | 'compare' | 'validation'
  const [activeLens, setActiveLens] = useState('all')
  const [showCompare, setShowCompare] = useState(false)
  const [compareLeftMode, setCompareLeftMode] = useState('verbatim')
  const [syncScroll, setSyncScroll] = useState(true)
  const [selectedSentence, setSelectedSentence] = useState(null)

  const leftScrollRef = useRef(null)
  const rightScrollRef = useRef(null)
  const isSyncingLeft = useRef(false)
  const isSyncingRight = useRef(false)

  const highlightedDoc = data?.highlighted_document || {}
  const rawOriginalHtml = highlightedDoc.original_html || ''
  const rawSnippetHtml = highlightedDoc.snippet_html || ''

  const normalizedOrig = useMemo(() => normalizeDocumentDom(rawOriginalHtml, false), [rawOriginalHtml])
  const normalizedHl = useMemo(() => normalizeDocumentDom(rawSnippetHtml, true), [rawSnippetHtml])

  if (!data) return null

  const isRedesign = data.type === 'redesign'
  if (!isRedesign) {
    return (
      <div className="plain-chat">
        <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{data.message || JSON.stringify(data)}</div>
      </div>
    )
  }

  const { what_this_is_about, what_you_need_to_do = {} } = data

  const sourceFilename =
    highlightedDoc.source_filename ||
    documentMetadata?.filename ||
    highlightedDoc.filename ||
    'Customer_Communication.txt'

  const subtitleText =
    what_this_is_about ||
    what_you_need_to_do.summary ||
    'Key sentences and paragraphs highlighted for immediate customer communication clarity.'

  const counts = normalizedHl.counts
  const sentenceItems = normalizedHl.items
  const originalViewUrl = highlightedDoc.original_view_url || documentMetadata?.view_url || null
  const activeInsight = selectedSentence || sentenceItems[0] || null

  const getCleanStandaloneHtml = () =>
    buildInteractiveStandaloneHtml(
      sourceFilename,
      subtitleText,
      normalizedOrig.html,
      normalizedHl.html,
      counts
    )

  const handleDownloadHighlighted = () => {
    const content = getCleanStandaloneHtml()
    const blob = new Blob([content], { type: 'text/html;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = highlightedDoc.filename || `highlighted_${sourceFilename}.html`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const handleOpenInSideViewer = () => {
    if (!onOpenDocument) return
    const content = getCleanStandaloneHtml()
    const blob = new Blob([content], { type: 'text/html;charset=utf-8' })
    const blobUrl = URL.createObjectURL(blob)
    onOpenDocument({
      name: sourceFilename,
      filename: sourceFilename,
      view_url: blobUrl,
      viewUrl: blobUrl,
      url: highlightedDoc.download_url || blobUrl
    })
  }

  const handleDocumentClick = (e) => {
    const mark = e.target.closest('mark[data-category]')
    if (!mark) return
    const cat = mark.getAttribute('data-category') || 'core_message'
    const label = mark.getAttribute('data-label') || CAT_LABELS[cat] || 'Key Sentence'
    const note = mark.getAttribute('data-note') || ''
    setSelectedSentence({
      category: cat,
      label,
      note,
      verbatim_text: (mark.textContent || '').trim()
    })
  }

  const handleLeftScroll = () => {
    if (!syncScroll || isSyncingLeft.current) {
      isSyncingLeft.current = false
      return
    }
    const left = leftScrollRef.current
    const right = rightScrollRef.current
    if (!left || !right) return
    isSyncingRight.current = true
    const ratio = left.scrollTop / Math.max(1, left.scrollHeight - left.clientHeight)
    right.scrollTop = ratio * Math.max(0, right.scrollHeight - right.clientHeight)
  }

  const handleRightScroll = () => {
    if (!syncScroll || isSyncingRight.current) {
      isSyncingRight.current = false
      return
    }
    const left = leftScrollRef.current
    const right = rightScrollRef.current
    if (!left || !right) return
    isSyncingLeft.current = true
    const ratio = right.scrollTop / Math.max(1, right.scrollHeight - right.clientHeight)
    left.scrollTop = ratio * Math.max(0, left.scrollHeight - left.clientHeight)
  }

  return (
    <div className={`claria-result claria-doc-viewer-mode filter-mode-${activeLens}`}>
      <div className="claria-file-viewer-card">
        {/* 1. CLEAN DOCUMENT VIEWER HEADER */}
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
                <strong className="claria-file-name">{sourceFilename}</strong>
              </div>
              {what_you_need_to_do?.summary && (
                <div className="claria-file-subtitle">{what_you_need_to_do.summary}</div>
              )}
            </div>
          </div>

          <div className="claria-viewer-actions">
            {data.downloads?.clean_pdf?.download_url ? (
              <a
                className="claria-tool-btn primary"
                href={absApiUrl(data.downloads.clean_pdf.download_url)}
                download={data.downloads.clean_pdf.filename || `${sourceFilename}_Redesigned.pdf`}
                style={{ textDecoration: 'none' }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                <span>Download Redesigned PDF</span>
              </a>
            ) : (
              <button
                type="button"
                className="claria-tool-btn primary"
                onClick={handleDownloadHighlighted}
              >
                <span>Download Output</span>
              </button>
            )}
            {data.downloads?.clean_docx?.download_url && (
              <a
                className="claria-tool-btn"
                href={absApiUrl(data.downloads.clean_docx.download_url)}
                download={data.downloads.clean_docx.filename || `${sourceFilename}_Redesigned.docx`}
                style={{ textDecoration: 'none' }}
              >
                <span>Download DOCX</span>
              </a>
            )}
            {onOpenDocument && (
              <button
                type="button"
                className="claria-tool-btn"
                onClick={handleOpenInSideViewer}
                title="Open in side viewer"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                  <polyline points="15 3 21 3 21 9" />
                  <line x1="10" y1="14" x2="21" y2="3" />
                </svg>
                <span>Open in Viewer</span>
              </button>
            )}
          </div>
        </div>

        {/* 4 CLEAN DELIVERABLE TABS (Redesigned | Original | Compare | Validation) */}
        <div className="claria-watchout-filter-bar">
          {[
            ['redesigned', '1. Redesigned Communication'],
            ['original', '2. Original Document'],
            ['compare', '3. Original vs. Redesigned'],
            ['validation', '4. Validation Report'],
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
        {deliverableTab === 'redesigned' && (() => {
          let rd = data.redesigned_document || {}
          const hasBackendRedesign = Boolean(
            rd.introduction || (rd.checklist && rd.checklist.length) || (rd.sections && rd.sections.length)
          )
          if (!hasBackendRedesign) {
            const rawLines = (highlightedDoc.raw_text || '')
              .split(/\r?\n/)
              .map(l => l.trim())
              .filter(Boolean)
            const dateMatch = (highlightedDoc.raw_text || '').match(
              /\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b/i
            )
            const bulletLines = rawLines
              .filter(l => /^(?:[•\-*▪▸]|\d+[.)])\s+/.test(l))
              .map(l => l.replace(/^(?:[•\-*▪▸]|\d+[.)])\s+/, '').trim())
            const actionSentences = sentenceItems.filter(s => s.category === 'what_to_do').map(s => s.verbatim_text)
            const impactSentences = sentenceItems.filter(s => s.category === 'customer_impact').map(s => s.verbatim_text)
            const coreSentences = sentenceItems.filter(s => s.category === 'core_message').map(s => s.verbatim_text)
            rd = {
              title: `Let's complete your ${sourceFilename.replace(/\.[^/.]+$/, '').replace(/[_-]+/g, ' ')}`,
              introduction: what_this_is_about || coreSentences[0] || what_you_need_to_do?.summary || rawLines[0] || '',
              deadline: dateMatch ? dateMatch[1] : '',
              checklist: bulletLines.length > 0 ? bulletLines : actionSentences.slice(0, 6),
              what_happens_next: coreSentences[1] || impactSentences[0] || '',
              how_to_submit: actionSentences.find(s => /submit|portal|manager|channel|email|upload/i.test(s)) || '',
              need_help: rawLines.find(l => /contact|relationship manager|help|support|clarification/i.test(l)) || '',
              sections: [],
              mandatory_disclosures: impactSentences.length > 0 ? impactSentences : rawLines.slice(-3),
              tone_applied: 'Customer-Friendly & Clear',
              plain_text: [
                what_this_is_about,
                what_you_need_to_do?.summary,
                ...(bulletLines.length > 0 ? bulletLines : actionSentences),
                ...impactSentences,
              ].filter(Boolean).join('\n\n'),
            }
          }
          const deadlineVal = rd.deadline || rd.call_to_action?.deadline
          const checklistItems = (rd.checklist && rd.checklist.length > 0)
            ? rd.checklist
            : (rd.sections || []).filter(s => (s.stage || '').toLowerCase() === 'action').flatMap(s => s.bullets || s.paragraphs || [])
          const obligations = rd.mandatory_disclosures || []
          const appliedTone = rd.tone_applied || 'Professional & Clear'
          const userInst = rd.user_instruction || ''
          const showCustomInst = userInst && !userInst.startsWith('Redesign professionally for clarity')
          return (
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

              <h2 className="claria-rd-headline">{rd.title || sourceFilename}</h2>
              {rd.introduction && <p className="claria-rd-intro">{rd.introduction}</p>}

              {deadlineVal && deadlineVal !== '[TO BE CONFIRMED]' && (
                <div className="claria-rd-deadline-card">
                  <span className="claria-rd-deadline-label">YOUR SUBMISSION DEADLINE</span>
                  <strong className="claria-rd-deadline-val">{deadlineVal}</strong>
                  <span className="claria-rd-deadline-sub">Please complete your submission on or before this date.</span>
                </div>
              )}

              {checklistItems.length > 0 && (
                <div className="claria-rd-block">
                  <h3>Your document / action checklist</h3>
                  <ul className="claria-rd-checklist">
                    {checklistItems.map((item, i) => <li key={i}>{item}</li>)}
                  </ul>
                </div>
              )}

              {rd.what_happens_next && (
                <div className="claria-rd-block">
                  <h3>What happens next?</h3>
                  <p>{rd.what_happens_next}</p>
                </div>
              )}

              {rd.how_to_submit && (
                <div className="claria-rd-block">
                  <h3>How to submit</h3>
                  <p>{rd.how_to_submit}</p>
                </div>
              )}

              {(rd.sections || []).map((sec, idx) => (
                <div key={idx} className="claria-rd-block">
                  <h3>{sec.heading}</h3>
                  {(sec.paragraphs || []).map((p, pi) => <p key={pi}>{p}</p>)}
                  {(sec.bullets || []).length > 0 && (
                    <ul className="claria-rd-checklist">
                      {sec.bullets.map((b, bi) => <li key={bi}>{b}</li>)}
                    </ul>
                  )}
                </div>
              ))}

              {(rd.need_help || rd.closing) && (
                <div className="claria-rd-block">
                  <h3>Need help?</h3>
                  <p>{rd.need_help || rd.closing}</p>
                </div>
              )}

              {obligations.length > 0 && (
                <div className="claria-rd-obligations">
                  <h3>Important Obligations &amp; Legal Disclosures (Preserved)</h3>
                  {obligations.map((ob, oi) => <p key={oi}>{ob}</p>)}
                </div>
              )}
            </div>
          )
        })()}

        {/* TAB 2: ORIGINAL PRESERVED DOCUMENT */}
        {deliverableTab === 'original' && (
          <div className="claria-document-viewport" dangerouslySetInnerHTML={{ __html: normalizedOrig.html || `<pre style="white-space:pre-wrap">${highlightedDoc.raw_text || ''}</pre>` }} />
        )}

        {/* TAB 3: ORIGINAL VS REDESIGNED COMPARISON */}
        {deliverableTab === 'compare' && (() => {
          const rd = data.redesigned_document || {}
          const changes = data.comparison?.changes || []
          return (
            <div className="claria-redesign-compare">
              <div className="claria-compare-grid">
                <div className="claria-compare-pane">
                  <div className="claria-compare-pane-header">
                    <div className="claria-pane-title">
                      <span className="claria-pane-dot orig" />
                      <strong>ORIGINAL FORMAL COMMUNICATION</strong>
                    </div>
                  </div>
                  <div className="claria-compare-pane-body" dangerouslySetInnerHTML={{ __html: normalizedOrig.html || `<pre style="white-space:pre-wrap">${highlightedDoc.raw_text || ''}</pre>` }} />
                </div>
                <div className="claria-compare-pane">
                  <div className="claria-compare-pane-header">
                    <div className="claria-pane-title">
                      <span className="claria-pane-dot hl" />
                      <strong>REDESIGNED CUSTOMER-FRIENDLY VERSION</strong>
                    </div>
                  </div>
                  <div className="claria-compare-pane-body">
                    <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0, lineHeight: 1.6 }}>
                      {rd.plain_text || rd.introduction || ''}
                    </pre>
                  </div>
                </div>
              </div>
              {changes.length > 0 && (
                <div className="claria-rd-changes-box">
                  <h4>What Changed, What Was Retained &amp; Why</h4>
                  {changes.slice(0, 8).map((ch, ci) => (
                    <div key={ci} className="claria-rd-change-row">
                      <span className="claria-rd-change-cat">{ch.category || ch.change_type || 'Restructured'}</span>
                      <div>{ch.reason || ch.explanation || ch.new_content || ch.original_content}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })()}

        {/* TAB 4: VALIDATION REPORT */}
        {deliverableTab === 'validation' && (() => {
          const fv = data.fact_verification || {}
          const verifiedFacts = fv.verified_facts || fv.facts || []
          const discrepancies = fv.discrepancies || []
          const tbc = data.redesigned_document?.tbc_placeholders || []
          return (
            <div className="claria-redesign-body">
              <div className="claria-rd-val-summary">
                <strong>Fact &amp; Clause Preservation:</strong> {fv.status || (discrepancies.length === 0 ? 'VERIFIED' : 'REVIEW REQUIRED')} · {verifiedFacts.length} source fact(s) checked · {discrepancies.length} discrepancy(ies)
              </div>
              {discrepancies.length > 0 && (
                <div className="claria-rd-obligations">
                  <h3>Flagged Discrepancies</h3>
                  {discrepancies.map((d, di) => (
                    <p key={di}><strong>{d.fact_type || 'Fact'}:</strong> Original `{d.original_value}` vs Output `{d.output_value}`</p>
                  ))}
                </div>
              )}
              {tbc.length > 0 && (
                <div className="claria-rd-obligations">
                  <h3>Missing Information ([TO BE CONFIRMED])</h3>
                  {tbc.map((t, ti) => <p key={ti}>{t}</p>)}
                </div>
              )}
              {verifiedFacts.length > 0 && (
                <div className="claria-rd-block">
                  <h3>Verified Source Figures, Dates &amp; Identifiers</h3>
                  <ul className="claria-rd-checklist">
                    {verifiedFacts.slice(0, 12).map((f, fi) => (
                      <li key={fi}><strong>{f.fact_type || 'Fact'}:</strong> {f.value || f.original_value} — {f.status || 'PRESERVED'}</li>
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
