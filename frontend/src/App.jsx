import { useState, useEffect, useRef } from 'react'
import ClariaSidebar from './components/ClariaSidebar.jsx'
import ClariaResultCard from './components/ClariaResultCard.jsx'
import DocumentViewer from './components/DocumentViewer.jsx'
import { redesignCommunication, toViewerDoc } from './services/api.js'

const SESSIONS_KEY = 'claria_sessions'

function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2)
}

function shorten(text, max) {
  return text.length > max ? text.slice(0, max) + '\u2026' : text
}

const GENERIC_CHAT_INPUTS = new Set([
  'hi', 'hello', 'hey', 'hola', 'hii', 'hiii', 'heyy', 'yo', 'sup',
  'how are you', 'how are u', 'how r u', 'how r you', 'how are you doing',
  'how are u doing', 'hows it going', 'how is it going', 'whats up',
  'good morning', 'good afternoon', 'good evening', 'greetings',
  'hi there', 'hello there', 'hey there', 'ok', 'okay', 'thanks', 'thank you'
])

function isGenericGreeting(text) {
  if (!text) return true
  const cleaned = text.trim().toLowerCase().replace(/[^\w\s]/g, '').replace(/\s+/g, ' ')
  if (cleaned.length <= 2) return true
  if (GENERIC_CHAT_INPUTS.has(cleaned)) return true
  return /^(?:hi+|h[ea]y+|h[ea]llo+|hlo|hola|greetings?|yo+|sup|namaste)(?:\s+(?:there|claria|agent|bot|all|team|friend|buddy))?$/.test(cleaned) ||
         /^(?:(?:hi+|h[ea]y+|h[ea]llo+|hlo)\s+)?(?:how|hw)\s+(?:r|are|re)\s+(?:u|you|yu)(?:\s+doing)?$/.test(cleaned) ||
         /^(?:hru|whats?\s+up|hows?\s+it\s+going|hows?\s+u)$/.test(cleaned)
}

function formatSmartTitle(text, fileName) {
  // 1. If user attached a file, clean file name
  if (fileName) {
    const base = fileName.replace(/\.[^/.]+$/, '').replace(/[-_]+/g, ' ').trim()
    if (base) {
      const formatted = base.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ')
      return shorten(formatted, 42)
    }
  }

  // 2. If user supplied text prompt, strip filler prefixes
  if (text && !isGenericGreeting(text)) {
    let clean = text.trim().replace(/\s+/g, ' ')
    clean = clean.replace(/^(?:can you|please|kindly|could you|would you|i want to|i need to|help me|can u|plz)\s+/i, '')
    clean = clean.replace(/^(?:rewrite|redesign|simplify|draft|review|check|improve|format|analyze)\s+(?:this|the|my|our)?\s*/i, '')
    clean = clean.replace(/^(?:document|communication|message|letter|notice|email|copy|text|draft)\s+(?:for|on|about|regarding)?\s*/i, '')
    clean = clean.replace(/^[?:!.,-\s]+/, '')
    if (clean.length > 2) {
      const capitalized = clean.charAt(0).toUpperCase() + clean.slice(1)
      return shorten(capitalized, 42)
    }
  }

  return 'New conversation'
}

function getClariaPreview(messages) {
  if (!messages || messages.length === 0) return 'Previous customer communication breakdown.'
  const aiMsg = messages.find(m => m.role === 'ai')
  if (aiMsg?.content?.what_this_is_about) {
    return shorten(aiMsg.content.what_this_is_about, 85)
  }
  const fileMsg = messages.find(m => m.file?.name)
  if (fileMsg?.file?.name) {
    return `Attached communication: ${fileMsg.file.name}`
  }
  const userMsg = messages.find(m => m.role === 'user' && m.content && !isGenericGreeting(m.content))
  if (userMsg?.content) {
    return shorten(userMsg.content, 85)
  }
  if (aiMsg?.content?.message) {
    return shorten(aiMsg.content.message, 85)
  }
  return 'Customer communication redesign & analysis.'
}

function titleFromResult(result) {
  if (!result || result.type === 'chat') return null
  if (result.what_this_is_about) {
    const clean = result.what_this_is_about.split('.')[0].trim()
    if (clean) return shorten(clean, 48)
  }
  return null
}

function loadSessions() {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY)
    const list = raw ? JSON.parse(raw) : []
    return list
      .filter(s => (s.messages || []).length > 0)
      .map(s => {
        let title = s.title || 'New conversation'
        // Filter out any corrupt HTML responses from earlier CloudFront 403 errors
        // and repair any legacy "notice.txt" short-prompt responses stored in localStorage
        let lastValidDocMsg = null
        const messages = (s.messages || [])
          .filter(m => {
            const str = typeof m.content === 'string' ? m.content : (typeof m.content?.message === 'string' ? m.content.message : '')
            return !str.includes('<!doctype') && !str.includes('<html')
          })
          .map(m => {
            if (m.role === 'ai' && m.content?.type === 'redesign') {
              const rawTxt = (m.content?.highlighted_document?.raw_text || '').trim()
              const srcName = m.content?.highlighted_document?.source_filename || ''
              const isShortPromptStub = (srcName === 'notice.txt' && rawTxt.split(/\s+/).length < 22 && !m.content?.redesigned_document)
              if (!isShortPromptStub && rawTxt.split(/\s+/).length >= 15) {
                lastValidDocMsg = m
              } else if (isShortPromptStub) {
                if (lastValidDocMsg?.content?.highlighted_document) {
                  return {
                    ...m,
                    document_metadata: lastValidDocMsg.document_metadata,
                    content: {
                      ...lastValidDocMsg.content,
                      what_this_is_about: m.content.what_this_is_about || lastValidDocMsg.content.what_this_is_about,
                      what_you_need_to_do: m.content.what_you_need_to_do || lastValidDocMsg.content.what_you_need_to_do,
                    },
                  }
                }
                return {
                  ...m,
                  content: {
                    type: 'chat',
                    message: [m.content?.what_this_is_about, m.content?.what_you_need_to_do?.summary].filter(Boolean).join('\n\n') || 'Ready to redesign your document.',
                  },
                }
              }
            }
            return m
          })

        // Upgrade unlocked sessions: prefer AI topic, or smart-stripped prompt/filename
        if (!s.titleLocked) {
          const lastRedesign = [...messages].reverse().find(m => m.role === 'ai' && m.content?.type === 'redesign')
          const rt = lastRedesign ? titleFromResult(lastRedesign.content) : null
          if (rt) {
            title = rt
          } else {
            const topicMsg = messages.find(m => m.role === 'user' && ((m.content && !isGenericGreeting(m.content)) || m.file?.name))
            if (topicMsg) {
              title = formatSmartTitle(topicMsg.content, topicMsg.file?.name)
            } else if (isGenericGreeting(title)) {
              title = 'New conversation'
            }
          }
        }

        return { ...s, title, messages }
      })
      .filter(s => (s.messages || []).length > 0)
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
  } catch {
    return []
  }
}

function saveSessions(sessions) {
  try {
    const valid = (sessions || []).filter(s => (s.messages || []).length > 0)
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(valid))
  } catch {
    // ignore
  }
}

export default function App() {
  const [view, setView] = useState('home') // 'home' | 'chat'
  const [sessions, setSessions] = useState(loadSessions)
  const [currentSessionId, setCurrentSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [inputText, setInputText] = useState('')
  const [homeInputText, setHomeInputText] = useState('')
  const [attachedFile, setAttachedFile] = useState(null)
  const [isThinking, setIsThinking] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [viewerDoc, setViewerDoc] = useState(null)

  function openDocument(meta) {
    let target = meta || {}
    if (!target.view_url && !target.viewUrl && !target.url) {
      const aiWithDoc = messages.find(m => m.document_metadata?.view_url || m.content?.document_metadata?.view_url)
      const found = aiWithDoc?.document_metadata || aiWithDoc?.content?.document_metadata
      if (found) {
        target = { ...target, ...found }
      }
    }
    setViewerDoc(toViewerDoc(target))
  }

  useEffect(() => {
    setViewerDoc(null)
  }, [currentSessionId])

  const homeFileInputRef = useRef(null)
  const chatFileInputRef = useRef(null)
  const messagesContainerRef = useRef(null)
  const sessionsRef = useRef(sessions)
  const prevLastRoleRef = useRef(null)
  const sessionJustChangedRef = useRef(false)

  useEffect(() => {
    sessionsRef.current = sessions
    saveSessions(sessions)
  }, [sessions])

  // Scroll logic: On session load -> TOP; On new AI reply -> TOP of response; On user message/thinking -> bottom
  useEffect(() => {
    const el = messagesContainerRef.current
    if (!el) return

    if (sessionJustChangedRef.current) {
      sessionJustChangedRef.current = false
      const timer = setTimeout(() => {
        const aiBubbles = el.querySelectorAll('.bubble.ai')
        const lastAi = aiBubbles[aiBubbles.length - 1]
        if (lastAi) {
          const elRect = el.getBoundingClientRect()
          const bubbleRect = lastAi.getBoundingClientRect()
          const targetTop = el.scrollTop + (bubbleRect.top - elRect.top) - 18
          el.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' })
        } else {
          el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
        }
      }, 50)
      prevLastRoleRef.current = messages[messages.length - 1]?.role
      return () => clearTimeout(timer)
    }

    const lastMsg = messages[messages.length - 1]
    const currentLastRole = lastMsg?.role
    const isNewAiReply = currentLastRole === 'ai' && (prevLastRoleRef.current === 'thinking' || lastMsg?.isNew)

    if (isNewAiReply) {
      const timer = setTimeout(() => {
        if (!el) return
        const aiBubbles = el.querySelectorAll('.bubble.ai')
        const lastAiBubble = aiBubbles[aiBubbles.length - 1]
        if (lastAiBubble) {
          const elRect = el.getBoundingClientRect()
          const bubbleRect = lastAiBubble.getBoundingClientRect()
          const targetTop = el.scrollTop + (bubbleRect.top - elRect.top) - 18
          el.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' })
        }
      }, 50)
      prevLastRoleRef.current = currentLastRole
      return () => clearTimeout(timer)
    } else if (currentLastRole === 'user' || isThinking) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    }

    prevLastRoleRef.current = currentLastRole
  }, [messages, isThinking])

  // Current session object
  const currentSession = sessions.find(s => s.id === currentSessionId)

  const goHome = () => {
    setCurrentSessionId(null)
    setMessages([])
    setAttachedFile(null)
    setView('home')
  }

  const openNewChat = (initialText = '', file = null) => {
    sessionJustChangedRef.current = true
    if (initialText || file) {
      const newId = generateId()
      const newSession = {
        id: newId,
        title: formatSmartTitle(initialText, file?.name),
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        date: 'TODAY',
        messages: []
      }
      setSessions(prev => [newSession, ...prev])
      setCurrentSessionId(newId)
      setMessages([])
      setView('chat')
      setDrawerOpen(false)
      setEditingTitle(false)
      handleSend(initialText, file, newId)
    } else {
      // Blank draft: NO empty session stored in history until user actually sends a message!
      setCurrentSessionId(null)
      setMessages([])
      setView('chat')
      setDrawerOpen(false)
      setEditingTitle(false)
    }
  }

  const selectSession = (sessionId) => {
    const s = sessions.find(item => item.id === sessionId)
    if (!s) return
    sessionJustChangedRef.current = true
    setCurrentSessionId(s.id)
    setMessages(s.messages || [])
    setView('chat')
    setDrawerOpen(false)
    setEditingTitle(false)
    setTimeout(() => {
      const el = messagesContainerRef.current
      if (el) {
        const aiBubbles = el.querySelectorAll('.bubble.ai')
        const lastAi = aiBubbles[aiBubbles.length - 1]
        if (lastAi) {
          const elRect = el.getBoundingClientRect()
          const bubbleRect = lastAi.getBoundingClientRect()
          const targetTop = el.scrollTop + (bubbleRect.top - elRect.top) - 18
          el.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' })
        } else {
          el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
        }
      }
    }, 60)
  }

  const renameSession = (id, newTitle) => {
    setSessions(prev => prev.map(s => s.id === id ? { ...s, title: newTitle, titleLocked: true } : s))
  }

  const deleteSession = (id) => {
    const next = sessionsRef.current.filter(s => s.id !== id)
    sessionsRef.current = next
    saveSessions(next)
    setSessions(next)

    if (id === currentSessionId) {
      setCurrentSessionId(null)
      setMessages([])
      setView('chat')
      setDrawerOpen(false)
      setEditingTitle(false)
    }
  }

  function commitTitle() {
    const v = titleDraft.trim()
    if (currentSessionId && v && v !== currentSession?.title) {
      renameSession(currentSessionId, v)
    }
    setEditingTitle(false)
  }

  const handleSend = async (textToSend, fileToSend, targetSessionId = currentSessionId) => {
    const content = (textToSend !== undefined ? textToSend : inputText).trim()
    const file = fileToSend !== undefined ? fileToSend : attachedFile

    if (!content && !file) return

    const isHomeStart = view === 'home' || !targetSessionId
    let activeId = (!isHomeStart && targetSessionId) ? targetSessionId : generateId()
    if (isHomeStart) {
      setCurrentSessionId(activeId)
      setView('chat')
    }

    const initialSessionTitle = formatSmartTitle(content, file?.name)
    const newSession = {
      id: activeId,
      title: initialSessionTitle,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      date: 'TODAY',
      updatedAt: Date.now(),
      messages: []
    }

    setInputText('')
    setAttachedFile(null)

    const userMessage = {
      id: generateId(),
      role: 'user',
      content: content,
      file: file ? { name: file.name, size: file.size } : null,
      timestamp: new Date().toLocaleTimeString()
    }

    const baseMsgs = (!isHomeStart && currentSession) ? (currentSession.messages || []) : []
    const nextMessages = [...baseMsgs, userMessage]
    setMessages(nextMessages)
    setIsThinking(true)

    setSessions(prev => {
      const existing = prev.find(s => s.id === activeId)
      const updated = existing
        ? { ...existing, updatedAt: Date.now(), messages: nextMessages }
        : { ...newSession, messages: nextMessages }
      return [updated, ...prev.filter(s => s.id !== activeId)]
    })

    const isRetryOrRefine = !file && /\b(retry|try again|re-?analyze|redo|more specific|be more specific|more detail|deeper)\b/i.test(content || '')
    const priorFileMsg = isRetryOrRefine
      ? [...nextMessages].reverse().find(m => m.role === 'user' && typeof File !== 'undefined' && m.file instanceof File)
      : null
    const effectiveFile = file || priorFileMsg?.file || null
    const lastRedesignMsg = !effectiveFile
      ? [...nextMessages].reverse().find(m => m.role === 'ai' && m.content?.type === 'redesign')
      : null
    const activeDocumentId = lastRedesignMsg?.content?.document_id || ''
    const activeDocumentText = lastRedesignMsg?.content?.highlighted_document?.raw_text || ''
    const activeDocumentFilename =
      lastRedesignMsg?.content?.highlighted_document?.source_filename ||
      lastRedesignMsg?.document_metadata?.filename ||
      lastRedesignMsg?.content?.document_metadata?.filename ||
      ''

    // Build memory history
    const historyPayload = nextMessages
      .filter(m => m.role === 'user' || m.role === 'ai')
      .slice(-6)
      .map(m => ({
        role: m.role,
        content: typeof m.content === 'string'
          ? m.content
          : JSON.stringify({
              type: m.content?.type,
              what_this_is_about: m.content?.what_this_is_about,
              what_you_need_to_do: m.content?.what_you_need_to_do,
              message: m.content?.message,
              highlights: (m.content?.highlighted_document?.watchout_items || m.content?.sentence_highlights || []).slice(0, 12).map(h => ({
                category: h.category,
                text: h.verbatim_text || h.verbatim_sentence,
                note: h.note || h.plain_meaning,
              })),
            }).slice(0, 2400)
      }))

    try {
      const [responseData] = await Promise.all([
        redesignCommunication({
          file: effectiveFile,
          text: content,
          conversationHistory: historyPayload,
          activeDocumentId,
          activeDocumentText,
          activeDocumentFilename,
        }),
        new Promise(res => setTimeout(res, 900))
      ])

      const docMeta = responseData.document_metadata
      const updatedUserMsg = docMeta && userMessage.file
        ? { ...userMessage, file: { ...userMessage.file, ...docMeta } }
        : userMessage

      const aiMessage = {
        id: generateId(),
        role: 'ai',
        content: responseData,
        document_metadata: docMeta,
        isNew: true,
        timestamp: new Date().toLocaleTimeString()
      }

      const finalMessages = [...nextMessages.slice(0, -1), updatedUserMsg, aiMessage]
      setMessages(finalMessages)

      // Auto title session and move to 1st in recent list
      setSessions(prev => {
        const target = prev.find(s => s.id === activeId)
        if (!target) return prev
        let updatedTitle = target.title
        if (!target.titleLocked) {
          const resultTitle = titleFromResult(responseData)
          if (resultTitle) {
            updatedTitle = resultTitle
          } else if (file) {
            updatedTitle = formatSmartTitle('', file.name)
          } else if (content && !isGenericGreeting(content)) {
            updatedTitle = formatSmartTitle(content)
          }
        }
        const updated = {
          ...target,
          title: updatedTitle,
          updatedAt: Date.now(),
          messages: finalMessages,
        }
        return [updated, ...prev.filter(s => s.id !== activeId)]
      })
    } catch (err) {
      const errorMessage = {
        id: generateId(),
        role: 'ai',
        content: {
          type: 'chat',
          message: `Unable to connect to CLARIA Intelligence Engine: ${err.message || 'Please check your connection.'}`
        },
        isNew: true,
        timestamp: new Date().toLocaleTimeString()
      }
      setMessages([...nextMessages, errorMessage])
    } finally {
      setIsThinking(false)
    }
  }

  return (
    <div className="app">
      <div className="aurora"></div>

      {/* ==================== HOME VIEW ==================== */}
      {view === 'home' && (
        <section id="home">
          <header>
            <div className="word" onClick={goHome} style={{ cursor: 'pointer' }}>CLARIA</div>
            <button className="enter" onClick={() => openNewChat()} type="button">
              ENTER WORKSPACE ↗
            </button>
          </header>

          <main className="home">
            <div className="eyebrow">CUSTOMER COMMUNICATIONS REDESIGN</div>
            <h1>
              Long message.<br />
              <span>Clear meaning.</span>
            </h1>
            <p className="sub">
              An enterprise AI space transforming complex, legal, and intimidating communications into crystal-clear clarity and immediate next actions.
            </p>

            <div className="promptGlow">
              <div className="prompt">
                <input
                  ref={homeFileInputRef}
                  className="fileInput"
                  type="file"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) setAttachedFile(f)
                  }}
                />
                <button
                  className="startAttach"
                  type="button"
                  aria-label="Add file"
                  title="Attach communication (PDF, DOCX, TXT)"
                  onClick={() => homeFileInputRef.current?.click()}
                >
                  <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="m21.4 11.6-8.9 8.9a6 6 0 0 1-8.5-8.5l9.3-9.3a4 4 0 0 1 5.7 5.7l-9.3 9.3a2 2 0 0 1-2.8-2.8l8.6-8.6" />
                  </svg>
                </button>

                <input
                  value={homeInputText}
                  onChange={(e) => setHomeInputText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      openNewChat(homeInputText, attachedFile)
                      setHomeInputText('')
                    }
                  }}
                  placeholder="Paste customer communication or attach a file..."
                  aria-label="Start redesign"
                />

                <button
                  className="send"
                  type="button"
                  aria-label="Send"
                  onClick={() => {
                    openNewChat(homeInputText, attachedFile)
                    setHomeInputText('')
                  }}
                >
                  <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M5 12h13" />
                    <path d="m13 7 5 5-5 5" />
                  </svg>
                </button>
              </div>
            </div>

            {attachedFile && (
              <div style={{ display: 'flex', justifyContent: 'center', width: '100%', marginTop: '12px' }}>
                <div className="filePill show">
                  <span>📎 Attached · {attachedFile.name}</span>
                  <button
                    type="button"
                    onClick={() => setAttachedFile(null)}
                    style={{ background: 'none', border: 0, color: '#f87171', cursor: 'pointer', fontWeight: 800, fontSize: '14px' }}
                  >
                    ✕
                  </button>
                </div>
              </div>
            )}

            <div className="recentGroup">
              <div className={`recentHead recentOnly${sessions.length === 0 ? ' recentEmpty' : ''}`}>
                <span>RECENT CONVERSATIONS</span>
              </div>

              <div className="cards">
                {sessions.length > 0 ? (
                  sessions.slice(0, 3).map((s) => (
                    <button key={s.id} className="card" onClick={() => selectSession(s.id)} type="button">
                      <small>{s.date} · {s.timestamp}</small>
                      <b>{s.title}</b>
                      <p>
                        {getClariaPreview(s.messages)}
                      </p>
                    </button>
                  ))
                ) : (
                  <div className="card emptyCard">
                    <small>NOTHING YET</small>
                    <b>No conversations yet</b>
                    <p>Type a message or attach a file above to begin.</p>
                  </div>
                )}
                {sessions.length > 3 && (
                  <button
                    type="button"
                    className="seeMoreOnly"
                    onClick={() => { setDrawerOpen(true); setView('chat'); }}
                  >
                    SEE MORE <span>+</span>
                  </button>
                )}
              </div>
            </div>
          </main>
        </section>
      )}

      {/* ==================== CHAT WORKSPACE ==================== */}
      {view === 'chat' && (
        <section className={`chatPage ${drawerOpen ? 'drawerOpen' : ''}`}>
          <div className={`layout${viewerDoc ? ' withViewer' : ''}`}>
            {/* Sidebar with Always-Visible Rename & Delete Buttons */}
            <ClariaSidebar
              sessions={sessions}
              currentSessionId={currentSessionId}
              onNew={() => openNewChat()}
              onLoad={(id) => selectSession(id)}
              onClose={() => setDrawerOpen(false)}
              isOpen={drawerOpen}
              onRename={renameSession}
              onDelete={deleteSession}
            />

            {/* Main Chat Area */}
            <main className="chat">
              <div className="chatHead">
                <div>
                  {editingTitle ? (
                    <input
                      autoComplete="off"
                      autoFocus
                      className="titleInput"
                      value={titleDraft}
                      maxLength={60}
                      onChange={e => setTitleDraft(e.target.value)}
                      onBlur={commitTitle}
                      onKeyDown={e => {
                        if (e.key === 'Enter') commitTitle()
                        if (e.key === 'Escape') setEditingTitle(false)
                      }}
                    />
                  ) : (
                    <b
                      className={currentSession ? 'titleEditable' : ''}
                      title={currentSession ? 'Click to rename' : ''}
                      onClick={() => {
                        if (!currentSession) return
                        setTitleDraft(currentSession.title)
                        setEditingTitle(true)
                      }}
                    >
                      {currentSession?.title || 'New conversation'}
                    </b>
                  )}
                  <small>ENTERPRISE INTELLIGENCE WORKSPACE</small>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <button className="ghost" onClick={goHome} type="button">
                    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="m3 10 9-7 9 7" />
                      <path d="M5 9v11h14V9" />
                      <path d="M9 20v-6h6v6" />
                    </svg>
                    <span style={{ marginLeft: '7px' }}>HOME</span>
                  </button>
                </div>
              </div>

              {/* Messages feed: Auto-scrolls to the TOP of the AI card! */}
              <div className="messages" aria-live="polite" ref={messagesContainerRef}>
                {messages.length === 0 && (
                  <div style={{ textAlign: 'center', margin: 'auto', color: '#849bb4', maxWidth: '520px', padding: '20px' }}>
                    <div style={{ display: 'inline-flex', padding: '12px', borderRadius: '14px', background: 'rgba(7, 140, 255, 0.1)', border: '1px solid rgba(7, 140, 255, 0.25)', color: '#38bdf8', marginBottom: '14px' }}>
                      <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <line x1="16" y1="13" x2="8" y2="13" />
                        <line x1="16" y1="17" x2="8" y2="17" />
                      </svg>
                    </div>
                    <b style={{ display: 'block', color: '#fff', fontSize: '18px' }}>Ready to redesign customer communications</b>
                    <p style={{ fontSize: '14.5px', lineHeight: '1.65', marginTop: '10px' }}>
                      Upload a communication file (PDF, DOCX, HTML, TXT) or paste a customer notice below to transform it into a clear, customer-friendly redesigned document while preserving every fact, deadline, and contractual obligation.
                    </p>
                  </div>
                )}

                {messages.map((m) => (
                  <div
                    key={m.id}
                    className={`bubble ${m.role === 'user' ? `user${m.file ? ' userBubbleWithFile' : ''}` : 'ai'}`}
                  >
                    {m.role === 'user' ? (
                      <div>
                        {m.file && (
                          <button
                            type="button"
                            className="userFileCard"
                            onClick={() => openDocument(m.file)}
                            title="Open document"
                          >
                            <div className="userFileHeader">
                              <div className="userFileLeft">
                                <span className="userFileIcon" aria-hidden="true">
                                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                                    <polyline points="14 2 14 8 20 8" />
                                  </svg>
                                </span>
                                <div className="userFileInfo">
                                  <span className="userFileName" title={m.file.name}>{m.file.name}</span>
                                  <span className="userFileMeta">
                                    {m.file.size ? `${(m.file.size / 1024).toFixed(1)} KB` : 'DOCUMENT'}
                                  </span>
                                </div>
                              </div>
                              <span className="userFileViewBtn">Open</span>
                            </div>
                          </button>
                        )}
                        {m.content && !m.content.startsWith('[Uploaded Communication:') && !m.content.startsWith('[File:') && (
                          <div style={{ marginTop: m.file ? '8px' : '0' }}>{m.content}</div>
                        )}
                      </div>
                    ) : (
                      <ClariaResultCard
                        data={m.content}
                        documentMetadata={m.document_metadata || m.content?.document_metadata}
                        onOpenDocument={openDocument}
                        onApplyTone={(instruction) => handleSend(instruction, null)}
                      />
                    )}
                  </div>
                ))}

                {isThinking && (
                  <div className="thinking">
                    <span className="thinkName">CLARIA</span>
                    <span className="bars">
                      <i></i><i></i><i></i><i></i>
                    </span>
                  </div>
                )}
              </div>

              {/* Composer */}
              <div className="composerArea">
                {attachedFile && (
                  <div style={{ display: 'flex', justifyContent: 'center', width: '100%', margin: '0 auto 10px' }}>
                    <div className="attachedRow composerAttached">
                      <span className="attachChip">
                        <span className="attachName">{attachedFile.name}</span>
                        <button
                          type="button"
                          className="attachRemove"
                          aria-label={`Remove ${attachedFile.name}`}
                          onClick={() => { setAttachedFile(null); if (chatFileInputRef.current) chatFileInputRef.current.value = '' }}
                        >
                          ×
                        </button>
                      </span>
                    </div>
                  </div>
                )}
                <div className="composer">
                  <form onSubmit={(e) => { e.preventDefault(); handleSend(); }}>
                    <input
                      ref={chatFileInputRef}
                      className="fileInput"
                      type="file"
                      onChange={(e) => {
                        const f = e.target.files?.[0]
                        if (f) setAttachedFile(f)
                      }}
                    />
                    <button
                      className="plus"
                      type="button"
                      aria-label="Add file"
                      title="Attach file (PDF, Word, TXT)"
                      onClick={() => chatFileInputRef.current?.click()}
                    >
                      <svg className="icon" viewBox="0 0 24 24" width="18" height="18">
                        <path d="m21.4 11.6-8.9 8.9a6 6 0 0 1-8.5-8.5l9.3-9.3a4 4 0 0 1 5.7 5.7l-9.3 9.3a2 2 0 0 1-2.8-2.8l8.6-8.6" />
                      </svg>
                    </button>
                    <input
                      value={inputText}
                      onChange={(e) => setInputText(e.target.value)}
                      placeholder="Message CLARIA or attach customer communication..."
                      maxLength={1000}
                      autoComplete="off"
                      aria-label="Message"
                    />
                    <button className="chatSend" type="submit" aria-label="Send" disabled={isThinking}>
                      <svg className="icon" viewBox="0 0 24 24" width="18" height="18">
                        <path d="M5 12h13" />
                        <path d="m13 7 5 5-5 5" />
                      </svg>
                    </button>
                  </form>
                </div>
                <div className="fine">
                  ENTERPRISE BFSI · CLARIA COMMUNICATIONS AUDITOR · ZERO HALLUCINATIONS · SECURE &amp; SANITIZED
                </div>
              </div>
            </main>
            <DocumentViewer doc={viewerDoc} onClose={() => setViewerDoc(null)} />
          </div>
        </section>
      )}
    </div>
  )
}
