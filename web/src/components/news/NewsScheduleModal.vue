<template>
  <a-modal v-model:open="visible" title="定时调度配置" width="700px" :footer="null" destroyOnClose>
    <div class="schedule-list" v-if="!editing">
      <a-table
        :dataSource="store.schedules"
        :columns="columns"
        :loading="store.schedulesLoading"
        rowKey="id"
        size="small"
        :pagination="false"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'enabled'">
            <a-switch :checked="record.enabled" disabled size="small" />
          </template>
          <template v-if="column.key === 'actions'">
            <a-button type="link" size="small" @click="startEdit(record)">编辑</a-button>
          </template>
        </template>
      </a-table>

      <div class="schedule-actions">
        <a-button type="primary" ghost @click="startCreate">新建调度</a-button>
      </div>
    </div>

    <div class="schedule-form" v-else>
      <a-form layout="vertical">
        <a-form-item label="名称">
          <a-input v-model:value="form.name" placeholder="例: 每日新闻速递" />
        </a-form-item>
        <a-form-item label="启用">
          <a-switch v-model:checked="form.enabled" />
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="触发时间">
              <a-time-picker
                v-model:value="form.triggerTime"
                format="HH:mm"
                valueFormat="HH:mm"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="语言">
              <a-select v-model:value="form.language" :options="languageOptions" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="模型">
          <a-select
            v-model:value="form.model_spec"
            placeholder="例: openai:gpt-4o"
            allowClear
            :options="modelOptions"
            :loading="modelLoading"
          />
        </a-form-item>
        <a-form-item label="AI 评分阈值">
          <a-input-number
            v-model:value="form.ai_score_threshold"
            :min="0"
            :max="10"
            :step="0.5"
            style="width: 120px"
          />
        </a-form-item>

        <a-divider>源配置</a-divider>
        <a-form-item label="Source Config JSON">
          <a-textarea v-model:value="form.source_config_raw" :rows="8" placeholder="{}" />
        </a-form-item>

        <a-divider>Webhook</a-divider>
        <a-form-item>
          <a-checkbox v-model:checked="form.webhook_enabled">启用 Webhook</a-checkbox>
        </a-form-item>
        <template v-if="form.webhook_enabled">
          <a-form-item label="Webhook URL">
            <a-input v-model:value="form.webhook_url" placeholder="https://..." />
          </a-form-item>
          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item label="平台">
                <a-select v-model:value="form.webhook_platform" :options="platformOptions" />
              </a-form-item>
            </a-col>
            <a-col :span="12">
              <a-form-item label="投递方式">
                <a-select v-model:value="form.webhook_delivery" :options="deliveryOptions" />
              </a-form-item>
            </a-col>
          </a-row>
        </template>
      </a-form>

      <div class="form-actions">
        <a-button @click="editing = false">取消</a-button>
        <a-button type="primary" :loading="saving" @click="handleSave">保存</a-button>
      </div>
    </div>
  </a-modal>
</template>

<script setup>
import { ref, reactive, watch, onMounted } from 'vue'
import { useNewsStore } from '@/stores/news'
import { modelProviderApi } from '@/apis'

const store = useNewsStore()
const emit = defineEmits(['done'])
const visible = defineModel('open', { type: Boolean, default: false })
const editing = ref(false)
const editingId = ref(null)
const saving = ref(false)

const defaultSourceConfig = {
  sources: {
    hackernews: { enabled: true, fetch_top_stories: 20, min_score: 100 },
    rss: [
      {
        name: 'Simon Willison',
        url: 'https://simonwillison.net/atom/everything/',
        enabled: true,
        category: 'ai-tools'
      }
    ],
    reddit: {
      enabled: true,
      subreddits: [
        {
          subreddit: 'MachineLearning',
          enabled: true,
          sort: 'hot',
          time_filter: 'day',
          fetch_limit: 15,
          min_score: 50
        }
      ],
      fetch_comments: 5
    }
  },
  filtering: {
    ai_score_threshold: 6.0,
    time_window_hours: 24,
    max_items: null,
    category_groups: {},
    default_group: 'other',
    default_group_limit: null
  }
}

const form = reactive({
  name: 'default',
  enabled: true,
  triggerTime: '08:00',
  language: 'zh',
  model_spec: '',
  ai_score_threshold: 5.0,
  source_config_raw: JSON.stringify(defaultSourceConfig, null, 2),
  webhook_enabled: false,
  webhook_url: '',
  webhook_platform: 'generic',
  webhook_delivery: 'summary'
})

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '时间', dataIndex: 'trigger_time', key: 'time', width: 80 },
  { title: '语言', dataIndex: 'language', key: 'lang', width: 60 },
  { title: '启用', key: 'enabled', width: 60 },
  { title: '状态', dataIndex: 'last_run_status', key: 'last', width: 80 },
  { title: '', key: 'actions', width: 60 }
]

const modelLoading = ref(false)
const modelOptions = ref([])

async function loadModels() {
  modelLoading.value = true
  try {
    const resp = await modelProviderApi.getV2Models('chat')
    const providers = resp.data || {}
    const options = []
    for (const p of Object.values(providers)) {
      for (const m of p.models || []) {
        if (m.spec) {
          options.push({ value: m.spec, label: m.spec })
        }
      }
    }
    modelOptions.value = options
    if (options.length > 0 && !form.model_spec) {
      form.model_spec = options[0].value
    }
  } catch (e) {
    console.error('Failed to load models:', e)
    modelOptions.value = []
  } finally {
    modelLoading.value = false
  }
}

onMounted(loadModels)

const languageOptions = [
  { value: 'zh', label: '中文 (zh)' },
  { value: 'en', label: 'English (en)' }
]

const platformOptions = [
  { value: 'generic', label: '通用' },
  { value: 'feishu', label: '飞书' },
  { value: 'lark', label: 'Lark' },
  { value: 'dingtalk', label: '钉钉' },
  { value: 'slack', label: 'Slack' },
  { value: 'discord', label: 'Discord' }
]

const deliveryOptions = [
  { value: 'summary', label: '仅摘要' },
  { value: 'summary_and_items', label: '摘要 + 逐条详情' }
]

watch(visible, (val) => {
  if (val) store.fetchSchedules()
})

function resetForm() {
  editingId.value = null
  form.name = 'default'
  form.enabled = true
  form.triggerTime = '08:00'
  form.language = 'zh'
  form.model_spec = ''
  form.ai_score_threshold = 5.0
  form.source_config_raw = JSON.stringify(defaultSourceConfig, null, 2)
  form.webhook_enabled = false
  form.webhook_url = ''
  form.webhook_platform = 'generic'
  form.webhook_delivery = 'summary'
}

function startCreate() {
  resetForm()
  if (modelOptions.value.length > 0) {
    form.model_spec = modelOptions.value[0].value
  }
  editing.value = true
}

function startEdit(record) {
  editingId.value = record.id
  form.name = record.name
  form.enabled = record.enabled
  form.triggerTime = record.trigger_time
  form.language = record.language || 'zh'
  form.model_spec = record.model_spec || ''
  form.ai_score_threshold = record.ai_score_threshold ?? 5.0
  form.source_config_raw = JSON.stringify(record.source_config || defaultSourceConfig, null, 2)
  const wc = record.webhook_config
  if (wc && wc.enabled) {
    form.webhook_enabled = true
    form.webhook_url = wc.url || ''
    form.webhook_platform = wc.platform || 'generic'
    form.webhook_delivery = wc.delivery || 'summary'
  } else {
    form.webhook_enabled = false
    form.webhook_url = ''
    form.webhook_platform = 'generic'
    form.webhook_delivery = 'summary'
  }
  editing.value = true
}

async function handleSave() {
  saving.value = true
  try {
    let sourceConfig = defaultSourceConfig
    try {
      sourceConfig = JSON.parse(form.source_config_raw)
    } catch {}

    const payload = {
      name: form.name,
      enabled: form.enabled,
      trigger_time: form.triggerTime,
      language: form.language,
      model_spec: form.model_spec || null,
      ai_score_threshold: form.ai_score_threshold,
      source_config: sourceConfig
    }

    if (form.webhook_enabled && form.webhook_url) {
      payload.webhook_config = {
        enabled: true,
        url: form.webhook_url,
        platform: form.webhook_platform,
        delivery: form.webhook_delivery,
        layout: 'markdown'
      }
    }

    if (editingId.value) {
      await store.updateSchedule(editingId.value, payload)
    } else {
      await store.createSchedule(payload)
    }

    editing.value = false
    emit('done')
    await store.fetchSchedules()
  } catch (e) {
    console.error('Save schedule failed:', e)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped lang="less">
.schedule-list {
  .schedule-actions {
    margin-top: 16px;
    display: flex;
    justify-content: flex-end;
  }
}

.schedule-form {
  .form-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 16px;
  }
}
</style>
