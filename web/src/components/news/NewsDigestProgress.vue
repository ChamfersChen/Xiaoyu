<template>
  <div class="news-digest-progress" v-if="digest">
    <a-progress
      :percent="percent"
      :status="status === 'failed' ? 'exception' : undefined"
      :stroke-color="status === 'failed' ? undefined : 'var(--main-600)'"
    />
    <div class="stage-label">{{ stageLabel }}</div>
    <div class="error-message" v-if="digest.error_message">
      <a-alert type="error" :message="digest.error_message" banner />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  digest: { type: Object, default: null }
})

const stageMap = {
  fetching: '正在获取新闻来源...',
  analyzing: 'AI 分析评分中...',
  deduplicating: '去重中...',
  enriching: '背景富化中...',
  summarizing: '生成摘要中...',
  completed: '已完成',
  failed: '生成失败'
}

const status = computed(() => props.digest?.status || 'pending')
const stage = computed(() => props.digest?.progress_stage || '')
const percent = computed(() => props.digest?.progress_percent || 0)
const stageLabel = computed(() => stageMap[stage.value] || stage.value || '准备中...')
</script>

<style scoped lang="less">
.news-digest-progress {
  padding: 32px 24px;
  max-width: 480px;
  margin: 0 auto;

  .stage-label {
    text-align: center;
    margin-top: 12px;
    color: var(--gray-600);
    font-size: 14px;
  }

  .error-message {
    margin-top: 16px;
  }
}
</style>
