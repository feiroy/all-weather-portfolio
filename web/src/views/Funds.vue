<template>
  <div class="page no-tab">
    <SubBar title="基金检索" :fallback="`/a/${aid}/market`" />
    <div class="wrap narrow">
      <van-search v-model="q" placeholder="基金名称或 6 位代码，比如 沪深300 / 000961" shape="round" autofocus class="sb" />
      <van-loading v-if="loading" style="margin:24px 0" vertical>查找中…</van-loading>
      <van-cell-group inset v-else-if="rows.length">
        <van-cell v-for="r in rows" :key="r.code" :title="r.name" :label="r.code" is-link
                  :to="`/a/${aid}/market/fund/${r.code}`">
          <template #value><span class="src">{{ r.src }}</span></template>
        </van-cell>
      </van-cell-group>
      <p v-else-if="q.trim()" class="empty-tip">没找到。试试换个关键词，或直接输入 6 位代码</p>
      <template v-else-if="recent.length">
        <div class="sec-t"><span>最近看过</span><a class="clr" @click="clear">清空</a></div>
        <div class="chips"><router-link v-for="r in recent" :key="r.code" class="chip" :to="`/a/${aid}/market/fund/${r.code}`">{{ r.name }}</router-link></div>
      </template>
    </div>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get } from '../api'
import SubBar from '../components/SubBar.vue'
const aid = useRoute().params.aid
const q = ref(sessionStorage.getItem('aw-fq') || ''), rows = ref([]), loading = ref(false)
const recent = ref(JSON.parse(localStorage.getItem('aw-recent-funds') || '[]'))
let t = null
watch(q, v => {
  sessionStorage.setItem('aw-fq', v)
  clearTimeout(t)
  if (!v.trim()) { rows.value = []; return }
  t = setTimeout(async () => {
    loading.value = true
    try {
      const r = (await get(`/api/market/fund-search?q=${encodeURIComponent(v.trim())}`)).rows
      // 输了 6 位代码但名录里没有：也给一个直达入口
      rows.value = r.length || !/^\d{6}$/.test(v.trim()) ? r : [{ code: v.trim(), name: `代码 ${v.trim()}`, src: '直接查' }]
    } finally { loading.value = false }
  }, 300)
}, { immediate: true })
const clear = () => { localStorage.removeItem('aw-recent-funds'); recent.value = [] }
</script>
<style scoped>
.narrow{ max-width:640px !important; }
.sb{ background:transparent; padding:10px 12px; }
.src{ font-size:12px; color:var(--muted); }
.clr{ color:var(--brand); cursor:pointer; }
.chips{ flex-wrap:wrap; } .chips a{ text-decoration:none; }
</style>
