import axios from 'axios'

// Vite proxies /api to the Studio server on 8010 in development; in a built
// deployment the same server serves this bundle, so a relative base works for both.
const api = axios.create({ baseURL: '/api' })

export const getConfig = () => api.get('/config').then((r) => r.data)

export const uploadFeedback = (files) => {
  const body = new FormData()
  files.forEach((f) => body.append('files', f))
  return api
    .post('/uploads', body, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((r) => r.data)
}

export const useSampleCorpus = () => api.post('/uploads/sample').then((r) => r.data)

export const estimate = (uploadId, params) =>
  api.get(`/uploads/${uploadId}/estimate`, { params }).then((r) => r.data)

export const startRun = (body) => api.post('/runs', body).then((r) => r.data)

export const readRun = (runId) => api.get(`/runs/${runId}`).then((r) => r.data)

export const cancelRun = (runId) => api.post(`/runs/${runId}/cancel`).then((r) => r.data)

export const publishRules = (runId) =>
  api.post(`/runs/${runId}/publish`).then((r) => r.data)

export const rulesUrl = (runId) => `/api/runs/${runId}/rules.json`

// Server errors carry the real reason in `detail`; surfacing the axios message
// instead ("Request failed with status code 400") tells the operator nothing.
export const errorText = (err) =>
  err?.response?.data?.detail ||
  err?.response?.data?.error ||
  err?.message ||
  'Request failed'
