<template>
  <!-- 曲线下方的统一状态行：与 iframe 图表（chart_html.py 的 .state-line）同结构同样式。
       左边说明当前看的是哪一段，右边日历图标 + 可见区间的真实起止日期。 -->
  <div class="chart-state">
    <span class="cs-note">{{ note }}</span>
    <span class="cs-date">
      <svg class="cs-icon" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="4" y="5" width="16" height="15" rx="2" fill="none" />
        <path d="M8 3v5m8-5v5M4 10h16" />
      </svg>
      <span>{{ range || '—' }}</span>
    </span>
  </div>
</template>
<script setup>
defineProps({ note: { type: String, default: '' }, range: { type: String, default: '' } })
</script>
<style scoped>
/* 数值与 chart_html.py 的 .state-line / .date-line 保持一致 */
.chart-state{ display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap;
  margin:8px 0 2px; font-size:12px; color:#475569; font-variant-numeric:tabular-nums; }
.cs-date{ display:flex; align-items:center; gap:6px; margin-left:auto; }
.cs-icon{ width:17px; height:17px; fill:none; stroke:currentColor; stroke-width:1.5; vertical-align:middle; }
/* 断点与字号都照搬 chart_html.py 的 @media(max-width:520px)，窄屏下与 iframe 图完全一致 */
@media (max-width:520px){ .chart-state{ font-size:11px; } }
</style>
