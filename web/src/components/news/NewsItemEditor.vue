<template>
  <div class="news-item-editor">
    <div class="item-header" @click="expanded = !expanded">
      <span class="item-index">#{{ index }}</span>
      <span class="item-score">★ {{ displayScore }}</span>
      <span class="item-source">{{ item.source_type }}</span>
      <span class="item-title">{{ truncatedText }}</span>
      <span class="item-toggle">▸</span>
    </div>
    <div class="item-body" v-if="expanded">
      <div class="item-content">{{ displayText }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  item: { type: Object, required: true },
  index: { type: Number, required: true }
})

const expanded = ref(false)

const displayScore = computed(() => props.item.ai_score ?? props.item.score ?? '?')
const displayText = computed(() => {
  return props.item.background || props.item.metadata?.background || ''
})
const truncatedText = computed(() => {
  const text = displayText.value
  return text.length > 100 ? text.slice(0, 100) + '...' : text
})
</script>

<style scoped lang="less">
.news-item-editor {
  border: 1px solid var(--gray-200);
  border-radius: 6px;
  margin-bottom: 8px;
  overflow: hidden;

  .item-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    cursor: pointer;
    background: var(--gray-50);
    font-size: 13px;

    &:hover {
      background: var(--gray-100);
    }

    .item-index {
      color: var(--main-600);
      font-weight: 600;
      min-width: 28px;
    }

    .item-score {
      color: var(--gray-600);
      min-width: 50px;
    }

    .item-source {
      color: var(--gray-500);
      font-size: 12px;
      min-width: 60px;
    }

    .item-title {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .item-toggle {
      color: var(--gray-400);
    }
  }

  .item-body {
    padding: 12px 12px 16px;
    border-top: 1px solid var(--gray-200);
    font-size: 13px;
    line-height: 1.6;
    color: var(--gray-900);

    .item-content {
      white-space: pre-wrap;
      word-break: break-word;
    }
  }
}
</style>
