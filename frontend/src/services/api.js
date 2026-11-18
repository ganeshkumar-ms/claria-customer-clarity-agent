import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || ''

export async function redesignCommunication({ file, text, conversationHistory = [] }) {
  const formData = new FormData()
  if (file) {
    formData.append('file', file)
  }
  if (text) {
    formData.append('text', text)
  }
  formData.append('conversation_history', JSON.stringify(conversationHistory))

  const response = await axios.post(`${API_BASE}/api/redesign`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000,
  })

  return response.data
}

export async function refineDocument(docId, instruction) {
  const response = await axios.post(`${API_BASE}/api/documents/${encodeURIComponent(docId)}/refine`, {
    instruction,
  }, { timeout: 60000 })
  return response.data
}

export async function correctDocument(docId, { confirm = 'yes', corrections = [], actor = 'Editor' }) {
  const response = await axios.post(`${API_BASE}/api/documents/${encodeURIComponent(docId)}/correct`, {
    confirm,
    corrections,
    actor,
  }, { timeout: 60000 })
  return response.data
}

export async function compareVersions(docId, v1 = 0, v2 = 0) {
  const response = await axios.get(`${API_BASE}/api/documents/${encodeURIComponent(docId)}/compare`, {
    params: { v1, v2 },
  })
  return response.data
}

export async function approveDocument(docId, payload) {
  const response = await axios.post(`${API_BASE}/api/documents/${encodeURIComponent(docId)}/approve`, payload)
  return response.data
}

export async function getDashboard(filters = {}) {
  const response = await axios.get(`${API_BASE}/api/dashboard`, { params: filters })
  return response.data
}

export function absApiUrl(u) {
  if (!u) return null
  return u.startsWith('http') ? u : `${API_BASE}${u}`
}

export function toViewerDoc(meta) {
  if (!meta) return null
  const viewUrl = absApiUrl(meta.view_url || meta.viewUrl)
  const downloadUrl = absApiUrl(meta.url || meta.downloadUrl)

  return {
    name: meta.filename || meta.name || 'Document',
    viewUrl: viewUrl,
    downloadUrl: downloadUrl,
    preview: meta.preview || '',
    rawMeta: meta
  }
}
