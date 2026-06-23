<template>
  <a-modal
    v-model:open="visible"
    title="触发 AI 速递"
    width="640px"
    @ok="handleTrigger"
    :confirmLoading="triggering"
    ok-text="触发并查看"
    cancel-text="取消"
    destroyOnClose
  >
    <a-form layout="vertical">
      <a-form-item label="模型">
        <a-select
          v-model:value="form.model_spec"
          placeholder="例: openai:gpt-4o"
          allowClear
          :options="modelOptions"
          :loading="modelLoading"
        >
          <template #placeholder>选择或输入模型标识</template>
        </a-select>
      </a-form-item>

      <a-form-item label="语言">
        <a-select v-model:value="form.language" :options="languageOptions" />
      </a-form-item>

      <a-divider>源配置</a-divider>

      <a-form-item label="配置模式">
        <a-radio-group v-model:value="sourceMode">
          <a-radio value="default">使用默认配置</a-radio>
          <a-radio value="custom">自定义 JSON</a-radio>
        </a-radio-group>
      </a-form-item>

      <a-form-item v-if="sourceMode === 'custom'" label="Source Config JSON">
        <a-textarea
          v-model:value="form.source_config_raw"
          :rows="12"
          placeholder="输入 JSON 配置..."
        />
      </a-form-item>

      <a-divider>Webhook (可选)</a-divider>

      <a-form-item>
        <a-checkbox v-model:checked="form.webhook_enabled">启用 Webhook 投递</a-checkbox>
      </a-form-item>

      <template v-if="form.webhook_enabled">
        <a-form-item label="Webhook URL">
          <a-input v-model:value="form.webhook_url" placeholder="https://..." />
        </a-form-item>
        <a-form-item label="平台">
          <a-select v-model:value="form.webhook_platform" :options="platformOptions" />
        </a-form-item>
        <a-form-item label="投递方式">
          <a-select v-model:value="form.webhook_delivery" :options="deliveryOptions" />
        </a-form-item>
      </template>
    </a-form>
  </a-modal>
</template>

<script setup>
import { ref, reactive, watch, onMounted } from 'vue'
import { useNewsStore } from '@/stores/news'
import { modelProviderApi } from '@/apis'

const store = useNewsStore()
const emit = defineEmits(['done'])
const visible = defineModel('open', { type: Boolean, default: false })
const triggering = ref(false)
const sourceMode = ref('default')

const defaultSourceConfig = {
  sources: {
    github: [
      {
        type: 'repo_releases',
        owner: 'vllm-project',
        repo: 'vllm',
        enabled: true
      },
      {
        type: 'repo_releases',
        owner: 'ollama',
        repo: 'ollama',
        enabled: true
      },
      {
        type: 'repo_releases',
        owner: 'langchain-ai',
        repo: 'langgraph',
        enabled: true
      },
      {
        type: 'repo_releases',
        owner: 'open-webui',
        repo: 'open-webui',
        enabled: true
      },
      {
        type: 'repo_releases',
        owner: 'microsoft',
        repo: 'autogen',
        enabled: true
      },
      {
        type: 'repo_releases',
        owner: 'crewAIInc',
        repo: 'crewAI',
        enabled: true
      }
    ],

    hackernews: {
      enabled: true,
      fetch_top_stories: 50,
      min_score: 80
    },

    rss: [
      {
        name: 'Simon Willison',
        url: 'https://simonwillison.net/atom/everything/',
        enabled: true,
        category: 'ai'
      },
      {
        name: 'Latent Space',
        url: 'https://www.latent.space/feed',
        enabled: true,
        category: 'ai'
      },
      {
        name: 'Sebastian Raschka',
        url: 'https://magazine.sebastianraschka.com/feed',
        enabled: true,
        category: 'llm'
      },
      {
        name: 'Anthropic News',
        url: 'https://www.anthropic.com/news/rss.xml',
        enabled: true,
        category: 'model'
      },
      {
        name: 'OpenAI Blog',
        url: 'https://openai.com/news/rss.xml',
        enabled: true,
        category: 'model'
      },
      {
        name: 'Google DeepMind',
        url: 'https://deepmind.google/discover/blog/rss.xml',
        enabled: true,
        category: 'research'
      },
      {
        name: 'Hugging Face Blog',
        url: 'https://huggingface.co/blog/feed.xml',
        enabled: true,
        category: 'open-source-ai'
      }
    ],

    reddit: {
      enabled: true,
      subreddits: [
        {
          subreddit: 'LocalLLaMA',
          enabled: true,
          sort: 'hot',
          time_filter: 'day',
          fetch_limit: 30,
          min_score: 20
        },
        {
          subreddit: 'MachineLearning',
          enabled: true,
          sort: 'hot',
          time_filter: 'day',
          fetch_limit: 20,
          min_score: 50
        },
        {
          subreddit: 'singularity',
          enabled: true,
          sort: 'hot',
          time_filter: 'day',
          fetch_limit: 20,
          min_score: 50
        },
        {
          subreddit: 'OpenAI',
          enabled: true,
          sort: 'hot',
          time_filter: 'day',
          fetch_limit: 20,
          min_score: 30
        }
      ],
      users: [],
      fetch_comments: 10
    },

    twitter: {
      enabled: true,
      users: [
        'karpathy',
        'swyx',
        'ylecun',
        'jeremyphoward',
        'AndrewYNg',
        'sama',
        'AnthropicAI',
        'OpenAI',
        'GoogleDeepMind'
      ],
      fetch_limit: 20,
      fetch_reply_text: true,
      max_replies_per_tweet: 5,
      max_tweets_to_expand: 20,
      reply_min_likes: 20
    },

    ossinsight: {
      enabled: true,
      period: 'past_24_hours',
      languages: ['Python', 'TypeScript', 'Rust'],
      keywords: ['llm', 'agent', 'mcp', 'rag', 'ai', 'gpt', 'claude', 'qwen', 'deepseek'],
      min_stars: 20,
      max_items: 50
    }
  },

  filtering: {
    ai_score_threshold: 7.5,
    time_window_hours: 24,
    max_items: 50,

    category_groups: {
      model: 10,
      research: 10,
      agent: 10,
      'open-source-ai': 15,
      industry: 10
    },

    default_group: 'industry',
    default_group_limit: 10
  }
};

const form = reactive({
  model_spec: '',
  language: 'zh',
  source_config_raw: JSON.stringify(defaultSourceConfig, null, 2),
  webhook_enabled: false,
  webhook_url: '',
  webhook_platform: 'generic',
  webhook_delivery: 'summary'
})

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

watch(
  () => visible.value,
  (val) => {
    if (val) {
      sourceMode.value = 'default'
      form.model_spec = modelOptions.value.length > 0 ? modelOptions.value[0].value : ''
      form.language = 'zh'
      form.source_config_raw = JSON.stringify(defaultSourceConfig, null, 2)
      form.webhook_enabled = false
      form.webhook_url = ''
      form.webhook_platform = 'generic'
      form.webhook_delivery = 'summary'
    }
  }
)

async function handleTrigger() {
  triggering.value = true
  try {
    const payload = {
      model_spec: form.model_spec || null,
      language: form.language
    }

    if (sourceMode.value === 'custom') {
      try {
        payload.source_config = JSON.parse(form.source_config_raw)
      } catch {
        payload.source_config = null
      }
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

    const digest = await store.triggerDigest(payload)
    visible.value = false
    emit('done', digest)
  } catch (e) {
    // store.triggerDigest already shows error message
  } finally {
    triggering.value = false
  }
}
</script>
