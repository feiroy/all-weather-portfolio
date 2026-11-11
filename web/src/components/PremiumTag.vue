<template>
  <!-- 溢价徽标：场内 ETF「现价 ÷ 最新净值 − 1」。
       数据取不到时不渲染（不是显示 0%），别让人以为算过。 -->
  <span v-if="ok" class="pq" :class="[q.level, { calm }]" :title="title">{{ text }}</span>
</template>
<script setup>
import { computed } from 'vue'

const props = defineProps({
  q: { type: Object, default: null },      // /api/market/premium 或 /calc 里挂的 quote
  // 卖出单不报警：按现价成交，溢价高反而多卖钱。信息照给，颜色压成中性灰
  calm: { type: Boolean, default: false },
})
const ok = computed(() => !!(props.q && props.q.ok && props.q.premium != null))
const text = computed(() => {
  if (!ok.value) return ''
  const p = props.q.premium * 100
  if (p < 0) return `折价 ${Math.abs(p).toFixed(2)}%`
  return `溢价 +${p.toFixed(2)}%`
})
// 折算：现价 2.662 / 净值 2.3884（11/10）；交易所 IOPV 接口拿不到，这里是估算值
const title = computed(() => {
  if (!ok.value) return ''
  const q = props.q
  const nav = q.nav == null ? '—' : q.nav.toFixed(4)
  const day = (q.nav_date || '').slice(5).replace('-', '/')
  return `现价 ${q.price} ÷ 最新净值 ${nav}（${day}）− 1`
})
</script>
<style scoped>
.pq{ display:inline-block; font-size:11px; line-height:17px; padding:0 6px; border-radius:9px;
  font-weight:500; white-space:nowrap; font-variant-numeric:tabular-nums; }
.pq.ok{ color:#6B7280; background:#F3F4F6; }
.pq.warn{ color:#B45309; background:#FEF3C7; }
.pq.high{ color:#92400E; background:#FDE68A; }
.pq.block{ color:#B91C1C; background:#FEE2E2; }
.pq.calm{ color:#6B7280; background:#F3F4F6; }
</style>
