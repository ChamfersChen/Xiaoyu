<template>
  <a-modal
    v-model:open="visible"
    title="投递摘要"
    width="520px"
    @ok="handleDeliver"
    :confirmLoading="delivering"
    ok-text="投递"
    cancel-text="取消"
    destroyOnClose
  >
    <a-form layout="vertical">
      <a-form-item label="Webhook URL" required>
        <a-input
          v-model:value="url"
          placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
        />
      </a-form-item>

      <a-form-item label="平台">
        <a-select v-model:value="platform" :options="platformOptions" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup>
import { ref } from 'vue'
import { useNewsStore } from '@/stores/news'
import { message } from 'ant-design-vue'

const store = useNewsStore()
const emit = defineEmits(['done'])
const visible = defineModel('open', { type: Boolean, default: false })

const props = defineProps({
  digestId: { type: String, default: null }
})

const delivering = ref(false)
const url = ref('')
const platform = ref('generic')

const platformOptions = [
  { value: 'generic', label: '通用' },
  { value: 'feishu', label: '飞书' },
  { value: 'lark', label: 'Lark' },
  { value: 'dingtalk', label: '钉钉' },
  { value: 'slack', label: 'Slack' },
  { value: 'discord', label: 'Discord' }
]

async function handleDeliver() {
  if (!url.value.trim()) {
    message.warning('请输入 Webhook URL')
    return
  }

  delivering.value = true
  try {
    const result = await store.deliverWebhook(props.digestId, {
      url: url.value.trim(),
      platform: platform.value
    })
    if (result.status === 'success') {
      message.success('投递成功')
    } else {
      message.error('投递失败: ' + (result.error || '未知错误'))
    }
    visible.value = false
    emit('done', result)
  } catch (e) {
    message.error('投递失败: ' + (e.message || '请求异常'))
  } finally {
    delivering.value = false
  }
}
</script>
