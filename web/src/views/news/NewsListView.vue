<template>
  <div class="news-page">
    <PageHeader title="AI 速递" :show-border="true">
      <template #actions>
        <a-tooltip title="手动触发">
          <a-button type="primary" ghost @click="showTriggerModal = true">
            <Zap class="icon" :size="16" />
            触发
          </a-button>
        </a-tooltip>
        <a-tooltip title="定时调度">
          <a-button @click="showScheduleModal = true">
            <Clock class="icon" :size="16" />
            定时配置
          </a-button>
        </a-tooltip>
      </template>
    </PageHeader>

    <div class="news-body">
      <div class="news-sidebar">
        <div class="sidebar-search">
          <a-input-search
            v-model:value="searchText"
            placeholder="搜索摘要..."
            allowClear
            @search="handleSearch"
          />
        </div>
        <div class="sidebar-list" v-if="!store.loading">
          <div
            v-for="d in store.digests"
            :key="d.id"
            class="sidebar-item"
            :class="{ active: selectedId === d.id }"
            @click="selectDigest(d)"
          >
            <div class="item-date">{{ formatDate(d.digest_date) }}</div>
            <div class="item-meta">
              <span class="score" v-if="d.status === 'completed'"
                >★ {{ d.total_selected }}/{{ d.total_fetched }}</span
              >
              <a-tag v-if="d.status === 'running'" color="processing" class="status-tag"
                >运行中</a-tag
              >
              <a-tag v-else-if="d.status === 'pending'" color="default" class="status-tag"
                >等待中</a-tag
              >
              <a-tag v-else-if="d.status === 'failed'" color="error" class="status-tag">失败</a-tag>
              <a-tag v-else-if="d.status === 'cancelled'" color="default" class="status-tag"
                >已取消</a-tag
              >
            </div>
            <div class="item-title" v-if="d.title">{{ d.title }}</div>
          </div>
          <div v-if="store.hasMore" class="load-more">
            <a-button type="link" @click="loadMore">加载更多...</a-button>
          </div>
          <div v-if="store.digests.length === 0" class="empty-list">暂无摘要</div>
        </div>
        <div v-else class="sidebar-loading"><a-spin /></div>
      </div>

      <div class="news-detail">
        <div v-if="!currentDigest" class="detail-empty">
          <FileText class="icon" :size="48" />
          <p>选择一个摘要查看详情</p>
        </div>

        <template
          v-else-if="currentDigest.status === 'running' || currentDigest.status === 'pending'"
        >
          <div class="detail-running">
            <NewsDigestProgress :digest="currentDigest" />
            <div class="detail-actions">
              <a-button danger @click="handleCancelDigest(currentDigest.id)">
                <X class="icon" :size="14" />
                取消任务
              </a-button>
            </div>
          </div>
        </template>

        <template v-else-if="currentDigest.status === 'failed'">
          <NewsDigestProgress :digest="currentDigest" />
          <div class="detail-actions">
            <a-button @click="retryDigest(currentDigest.id)">重试</a-button>
            <a-popconfirm
              title="确认删除该摘要?"
              description="删除后不可恢复"
              ok-text="确认删除"
              cancel-text="取消"
              placement="top"
              overlayClassName="delete-popconfirm"
              @confirm="handleDeleteDigest(currentDigest.id)"
            >
              <a-button danger>删除</a-button>
            </a-popconfirm>
          </div>
        </template>

        <template v-else>
          <div class="detail-header">
            <div class="detail-title">
              <h2>{{ currentDigest.title }}</h2>
              <span class="detail-date">{{ formatDate(currentDigest.digest_date) }}</span>
              <a-tag v-if="currentDigest.trigger_type === 'scheduled'">定时</a-tag>
              <a-tag v-else>手动</a-tag>
            </div>
            <div class="detail-toolbar">
              <a-segmented v-model:value="editMode" :options="editModeOptions" />
              <div class="toolbar-actions">
                <a-button size="small" @click="downloadMarkdown(currentDigest.id)">
                  <Download class="icon" :size="14" />
                  下载
                </a-button>
                <a-button size="small" @click="regenerateMarkdown(currentDigest.id)"
                  >重新生成</a-button
                >
                <a-popconfirm
                  title="确认删除该摘要?"
                  description="删除后不可恢复"
                  ok-text="确认删除"
                  cancel-text="取消"
                  placement="topRight"
                  overlayClassName="delete-popconfirm"
                  @confirm="handleDeleteDigest(currentDigest.id)"
                >
                  <a-button size="small" danger>
                    <Trash2 class="icon" :size="14" />
                    删除
                  </a-button>
                </a-popconfirm>
                <a-button
                  v-if="
                    currentDigest.webhook_config?.enabled &&
                    currentDigest.webhook_status !== 'success'
                  "
                  size="small"
                  @click="retryWebhook(currentDigest.id)"
                >
                  重试 Webhook
                </a-button>
              </div>
            </div>
            <div class="webhook-status" v-if="currentDigest.webhook_status">
              <a-tag
                :color="
                  currentDigest.webhook_status === 'success'
                    ? 'green'
                    : currentDigest.webhook_status === 'failed'
                      ? 'red'
                      : 'default'
                "
              >
                Webhook: {{ currentDigest.webhook_status }}
              </a-tag>
            </div>
          </div>

          <div class="detail-content">
            <div v-if="editMode === 'preview'" class="markdown-preview">
              <MarkdownPreview :content="currentDigest.raw_markdown || ''" />
            </div>
            <div v-else class="markdown-editor">
              <a-textarea
                v-model:value="editedMarkdown"
                :rows="20"
                placeholder="编辑 Markdown..."
              />
              <div class="editor-actions">
                <a-button type="primary" size="small" @click="saveEditedMarkdown">保存</a-button>
              </div>
            </div>
          </div>

          <div class="detail-items" v-if="currentDigest.items && currentDigest.items.length > 0">
            <h3>条目列表 ({{ currentDigest.items.length }})</h3>
            <NewsItemEditor
              v-for="(item, idx) in currentDigest.items"
              :key="idx"
              :digest-id="currentDigest.id"
              :item="item"
              :index="idx"
            />
          </div>
        </template>
      </div>
    </div>

    <NewsTriggerModal v-model:open="showTriggerModal" @done="onTriggerDone" />
    <NewsScheduleModal v-model:open="showScheduleModal" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useNewsStore } from '@/stores/news'
import { newsApi } from '@/apis'
import PageHeader from '@/components/shared/PageHeader.vue'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import NewsDigestProgress from '@/components/news/NewsDigestProgress.vue'
import NewsTriggerModal from '@/components/news/NewsTriggerModal.vue'
import NewsScheduleModal from '@/components/news/NewsScheduleModal.vue'
import NewsItemEditor from '@/components/news/NewsItemEditor.vue'
import { Zap, Clock, FileText, Download, Trash2, X } from 'lucide-vue-next'
import { message } from 'ant-design-vue'

const store = useNewsStore()
const showTriggerModal = ref(false)
const showScheduleModal = ref(false)
const selectedId = ref(null)
const editMode = ref('preview')
const editModeOptions = [
  { value: 'preview', label: '预览' },
  { value: 'edit', label: '编辑' }
]
const editedMarkdown = ref('')
const searchText = ref('')

const currentDigest = computed(() => store.currentDigest)

let pollTimer = null

onMounted(async () => {
  await store.fetchDigests()
  if (store.digests.length > 0) {
    selectDigest(store.digests[0])
  }
})

watch(editMode, (mode) => {
  if (mode === 'edit' && currentDigest.value) {
    editedMarkdown.value = currentDigest.value.raw_markdown || ''
  }
})

function formatDate(d) {
  if (!d) return ''
  return d
}

function selectDigest(digest) {
  selectedId.value = digest.id
  store.setCurrentDigest(null)
  editMode.value = 'preview'
  stopPolling()
  store.fetchDigest(digest.id).then((d) => {
    if (d && (d.status === 'running' || d.status === 'pending')) {
      startPolling(d.id)
    }
  })
}

function startPolling(id) {
  stopPolling()
  pollTimer = setInterval(async () => {
    const d = await store.fetchDigest(id)
    if (d && (d.status === 'completed' || d.status === 'failed')) {
      stopPolling()
    }
  }, 5000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function handleSearch() {
  store.setPage(1)
  store.fetchDigests({ status: searchText.value ? undefined : undefined })
}

function loadMore() {
  store.setPage(store.page + 1)
  store.fetchDigests()
}

async function onTriggerDone(digest) {
  if (digest) {
    selectDigest(digest)
  }
}

async function downloadMarkdown(id) {
  try {
    const blob = await newsApi.downloadDigest(id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `news-digest-${id.slice(0, 8)}.md`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    message.error('下载失败')
  }
}

async function regenerateMarkdown(id) {
  await store.regenerateMarkdown(id)
}

async function retryDigest(id) {
  message.info('重试功能待实现')
}

async function retryWebhook(id) {
  await store.retryWebhook(id)
}

async function handleCancelDigest(id) {
  stopPolling()
  await store.cancelDigest(id)
  if (selectedId.value === id) {
    await store.fetchDigest(id)
  }
}

async function handleDeleteDigest(id) {
  await store.deleteDigest(id)
  if (selectedId.value === id) {
    selectedId.value = null
    store.setCurrentDigest(null)
    if (store.digests.length > 0) {
      selectDigest(store.digests[0])
    }
  }
}

async function saveEditedMarkdown() {
  if (!currentDigest.value) return
  await store.updateDigestMarkdown(currentDigest.value.id, editedMarkdown.value)
  editMode.value = 'preview'
}
</script>

<style scoped lang="less">
.news-page {
  height: 100%;
  display: flex;
  flex-direction: column;

  .icon {
    vertical-align: middle;
  }
}

.news-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.news-sidebar {
  width: 300px;
  min-width: 300px;
  border-right: 1px solid var(--gray-200);
  display: flex;
  flex-direction: column;
  background: var(--gray-50);

  .sidebar-search {
    padding: 12px;
  }

  .sidebar-list {
    flex: 1;
    overflow-y: auto;
    padding: 0 8px 12px;

    .sidebar-item {
      padding: 10px 12px;
      border-radius: 6px;
      cursor: pointer;
      margin-bottom: 4px;

      &:hover {
        background: var(--gray-100);
      }

      &.active {
        background: var(--main-40);
        border-left: 3px solid var(--main-600);
      }

      .item-date {
        font-size: 12px;
        color: var(--gray-500);
        margin-bottom: 2px;
      }

      .item-meta {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-bottom: 2px;

        .score {
          font-size: 12px;
          color: var(--gray-600);
        }

        .status-tag {
          font-size: 11px;
          line-height: 18px;
        }
      }

      .item-title {
        font-size: 13px;
        color: var(--gray-900);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }

    .load-more {
      text-align: center;
      padding: 8px;
    }

    .empty-list {
      text-align: center;
      color: var(--gray-400);
      padding: 32px 0;
    }
  }

  .sidebar-loading {
    display: flex;
    justify-content: center;
    padding: 48px 0;
  }
}

.news-detail {
  flex: 1;
  overflow-y: auto;
  padding: 0 var(--page-padding) var(--page-padding);
  background: var(--main-0);

  .detail-running {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;

    > * {
      width: 100%;
    }
  }

  .detail-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--gray-400);

    .icon {
      margin-bottom: 12px;
    }
  }

  .detail-header {
    padding: 16px 0;
    border-bottom: 1px solid var(--gray-200);
    margin-bottom: 16px;

    .detail-title {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;

      h2 {
        margin: 0;
        font-size: 18px;
        font-weight: 600;
        color: var(--gray-2000);
      }

      .detail-date {
        font-size: 13px;
        color: var(--gray-500);
      }
    }

    .detail-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;

      .toolbar-actions {
        display: flex;
        gap: 6px;
      }
    }

    .webhook-status {
      margin-top: 8px;
    }
  }

  .detail-content {
    margin-bottom: 24px;

    .markdown-preview {
      min-height: 200px;
    }

    .markdown-editor {
      .editor-actions {
        margin-top: 8px;
        display: flex;
        justify-content: flex-end;
      }
    }
  }

  .detail-actions {
    padding: 16px;
    display: flex;
    justify-content: center;
    gap: 8px;
  }

  .detail-items {
    h3 {
      font-size: 15px;
      font-weight: 600;
      color: var(--gray-900);
      margin-bottom: 12px;
    }
  }
}

:global(.delete-popconfirm) {
  min-width: 220px;
}
</style>
