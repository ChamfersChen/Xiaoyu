<template>
  <div class="news-item-editor">
    <div class="item-header" @click="expanded = !expanded">
      <span class="item-index">#{{ index }}</span>
      <span class="item-score">★ {{ item.score || item.ai_score || '?' }}</span>
      <span class="item-source">{{ item.source_type }}</span>
      <span class="item-title">{{ item.title }}</span>
      <span class="item-toggle">{{ expanded ? '▾' : '▸' }}</span>
    </div>
    <div class="item-body" v-if="expanded">
      <a-form layout="vertical" size="small">
        <a-form-item label="摘要">
          <a-textarea
            v-model:value="editForm.summary"
            :rows="3"
            :placeholder="item.summary || ''"
          />
        </a-form-item>
        <a-form-item label="背景">
          <a-textarea
            v-model:value="editForm.background"
            :rows="2"
            :placeholder="item.background || ''"
          />
        </a-form-item>
        <a-form-item label="标签">
          <a-select
            v-model:value="editForm.tags"
            mode="tags"
            placeholder="输入标签后回车"
            style="width: 100%"
          />
        </a-form-item>
        <div class="item-actions">
          <a-button type="primary" size="small" :loading="saving" @click="handleSave"
            >保存修改</a-button
          >
          <a-button danger size="small" :loading="deleting" @click="handleDelete">删除</a-button>
          <a-button size="small" @click="expanded = false">取消</a-button>
        </div>
      </a-form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { useNewsStore } from '@/stores/news'

const props = defineProps({
  digestId: { type: String, required: true },
  item: { type: Object, required: true },
  index: { type: Number, required: true }
})

const emit = defineEmits(['deleted'])

const store = useNewsStore()
const expanded = ref(false)
const saving = ref(false)
const deleting = ref(false)

const editForm = reactive({
  summary: '',
  background: '',
  tags: []
})

watch(expanded, (val) => {
  if (val) {
    editForm.summary = props.item.summary || props.item.ai_summary || ''
    editForm.background = props.item.background || props.item.metadata?.background || ''
    editForm.tags = props.item.tags || props.item.ai_tags || []
  }
})

async function handleSave() {
  saving.value = true
  try {
    await store.updateDigestItem(props.digestId, props.index, {
      summary: editForm.summary,
      background: editForm.background,
      tags: editForm.tags
    })
  } finally {
    saving.value = false
  }
}

async function handleDelete() {
  deleting.value = true
  try {
    await store.deleteDigestItem(props.digestId, props.index)
    emit('deleted', props.index)
  } finally {
    deleting.value = false
  }
}
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
    padding: 12px;
    border-top: 1px solid var(--gray-200);

    .item-actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
    }
  }
}
</style>
