import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { newsApi } from '@/apis'
import { message } from 'ant-design-vue'

export const useNewsStore = defineStore('news', () => {
  const digests = ref([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(50)
  const loading = ref(false)
  const currentDigest = ref(null)
  const currentDigestLoading = ref(false)
  const schedules = ref([])
  const schedulesLoading = ref(false)

  const hasMore = computed(() => digests.value.length < total.value)

  async function fetchDigests(params = {}) {
    loading.value = true
    try {
      const resp = await newsApi.listDigests({
        page: page.value,
        page_size: pageSize.value,
        ...params
      })
      digests.value = resp.data || []
      total.value = resp.total || 0
    } catch (e) {
      console.error('Failed to fetch digests:', e)
    } finally {
      loading.value = false
    }
  }

  async function fetchDigest(id) {
    currentDigestLoading.value = true
    try {
      const resp = await newsApi.getDigest(id)
      currentDigest.value = resp.data || null
      return currentDigest.value
    } catch (e) {
      console.error('Failed to fetch digest:', e)
      currentDigest.value = null
      return null
    } finally {
      currentDigestLoading.value = false
    }
  }

  async function triggerDigest(data) {
    try {
      const resp = await newsApi.triggerDigest(data)
      const digest = resp.data
      if (digest) {
        digests.value.unshift(digest)
        total.value++
      }
      message.success('已触发 AI 速递')
      return digest
    } catch (e) {
      message.error('触发失败: ' + (e.message || '未知错误'))
      throw e
    }
  }

  async function cancelDigest(digestId) {
    try {
      await newsApi.cancelDigest(digestId)
      const idx = digests.value.findIndex((d) => d.id === digestId)
      if (idx >= 0) {
        digests.value[idx] = { ...digests.value[idx], status: 'cancelled' }
      }
      if (currentDigest.value && currentDigest.value.id === digestId) {
        currentDigest.value = { ...currentDigest.value, status: 'cancelled' }
      }
      message.success('任务已取消')
    } catch (e) {
      message.error('取消失败: ' + (e.message || '未知错误'))
      throw e
    }
  }

  async function deleteDigest(digestId) {
    try {
      await newsApi.deleteDigest(digestId)
      digests.value = digests.value.filter((d) => d.id !== digestId)
      total.value = Math.max(0, total.value - 1)
      if (currentDigest.value && currentDigest.value.id === digestId) {
        currentDigest.value = null
      }
      message.success('摘要已删除')
    } catch (e) {
      message.error('删除失败: ' + (e.message || '未知错误'))
      throw e
    }
  }

  async function updateDigestItem(digestId, itemIndex, updates) {
    try {
      const resp = await newsApi.updateItem(digestId, itemIndex, updates)
      message.success('条目已更新')
      return resp.data
    } catch (e) {
      message.error('更新失败: ' + (e.message || '未知错误'))
      throw e
    }
  }

  async function deleteDigestItem(digestId, itemIndex) {
    try {
      await newsApi.deleteItem(digestId, itemIndex)
      if (currentDigest.value && currentDigest.value.id === digestId) {
        currentDigest.value.items.splice(itemIndex, 1)
      }
      message.success('条目已删除')
    } catch (e) {
      message.error('删除失败: ' + (e.message || '未知错误'))
      throw e
    }
  }

  async function updateDigestMarkdown(digestId, rawMarkdown) {
    try {
      const resp = await newsApi.updateMarkdown(digestId, { raw_markdown: rawMarkdown })
      if (currentDigest.value && currentDigest.value.id === digestId) {
        currentDigest.value.raw_markdown = resp.data?.raw_markdown
      }
      message.success('Markdown 已保存')
      return resp.data?.raw_markdown
    } catch (e) {
      message.error('保存失败: ' + (e.message || '未知错误'))
      throw e
    }
  }

  async function regenerateMarkdown(digestId) {
    try {
      const resp = await newsApi.regenerateMarkdown(digestId)
      if (currentDigest.value && currentDigest.value.id === digestId) {
        currentDigest.value.raw_markdown = resp.data?.raw_markdown
      }
      message.success('Markdown 已重新生成')
      return resp.data?.raw_markdown
    } catch (e) {
      message.error('重新生成失败: ' + (e.message || '未知错误'))
      throw e
    }
  }

  async function retryWebhook(digestId) {
    try {
      const resp = await newsApi.retryWebhook(digestId)
      message.success('Webhook 已重试')
      return resp.data
    } catch (e) {
      message.error('Webhook 重试失败: ' + (e.message || '未知错误'))
      throw e
    }
  }

  async function deliverWebhook(digestId, data) {
    const resp = await newsApi.deliverWebhook(digestId, data)
    return resp.data
  }

  async function fetchSchedules() {
    schedulesLoading.value = true
    try {
      const resp = await newsApi.listSchedules()
      schedules.value = resp.data || []
    } catch (e) {
      console.error('Failed to fetch schedules:', e)
    } finally {
      schedulesLoading.value = false
    }
  }

  async function createSchedule(data) {
    try {
      const resp = await newsApi.createSchedule(data)
      schedules.value.unshift(resp.data)
      message.success('定时调度已创建')
      return resp.data
    } catch (e) {
      message.error('创建失败: ' + (e.message || '未知错误'))
      throw e
    }
  }

  async function updateSchedule(id, data) {
    try {
      const resp = await newsApi.updateSchedule(id, data)
      const idx = schedules.value.findIndex((s) => s.id === id)
      if (idx >= 0) schedules.value[idx] = resp.data
      message.success('定时调度已更新')
      return resp.data
    } catch (e) {
      message.error('更新失败: ' + (e.message || '未知错误'))
      throw e
    }
  }

  function setPage(n) {
    page.value = n
  }

  function setCurrentDigest(digest) {
    currentDigest.value = digest
  }

  return {
    digests,
    total,
    page,
    pageSize,
    loading,
    currentDigest,
    currentDigestLoading,
    schedules,
    schedulesLoading,
    hasMore,
    fetchDigests,
    fetchDigest,
    triggerDigest,
    cancelDigest,
    deleteDigest,
    updateDigestItem,
    deleteDigestItem,
    updateDigestMarkdown,
    regenerateMarkdown,
    retryWebhook,
    deliverWebhook,
    fetchSchedules,
    createSchedule,
    updateSchedule,
    setPage,
    setCurrentDigest
  }
})
