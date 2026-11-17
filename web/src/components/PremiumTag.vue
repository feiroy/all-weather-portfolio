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
// 折溢价是「同一天两个价」的关系：接口给的是最近同交易日的收盘价 vs 净值。
// 拿实时价配上一净值日净值，会把今天的涨跌算成溢价（511130 11/17 盘中就显示成
// 溢价 +0.50%，实际 11/16 是折价 0.34%）—— 所以 title 里把两个价和日期都写出来。
const title = computed(() => {
  if (!ok.value) return ''
  const q = props.q
  if (q.premium_date) {
    const day = q.premium_date.slice(5).replace('-', '/')
    return `${day} 收盘 ${q.premium_price} ÷ 同日净值 ${q.premium_base} − 1`
  }
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
