import { apiGet, apiPost, apiPut, apiDelete } from './base'

export const newsApi = {
  listDigests: (params) => apiGet('/api/news/digests', { params }),
  getDigest: (id) => apiGet(`/api/news/digests/${id}`),
  triggerDigest: (data) => apiPost('/api/news/digests/trigger', data),
  downloadDigest: (id) => apiGet(`/api/news/digests/${id}/download`, {}, true, 'blob'),
  updateItem: (id, index, data) => apiPut(`/api/news/digests/${id}/items/${index}`, data),
  deleteItem: (id, index) => apiDelete(`/api/news/digests/${id}/items/${index}`),
  updateMarkdown: (id, data) => apiPut(`/api/news/digests/${id}/markdown`, data),
  cancelDigest: (id) => apiPost(`/api/news/digests/${id}/cancel`),
  deleteDigest: (id) => apiDelete(`/api/news/digests/${id}`),
  regenerateMarkdown: (id) => apiPost(`/api/news/digests/${id}/regenerate`),
  retryWebhook: (id) => apiPost(`/api/news/digests/${id}/webhook/retry`),

  listSchedules: () => apiGet('/api/news/schedules'),
  createSchedule: (data) => apiPost('/api/news/schedules', data),
  updateSchedule: (id, data) => apiPut(`/api/news/schedules/${id}`, data)
}
