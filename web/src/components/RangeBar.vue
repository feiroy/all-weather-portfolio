<template>
  <!-- 全站唯一的区间控件：8 个统一区间 chip +（可选）日/月/年线分段。
       类名沿用 style.css 的 .chips / .chip / .seg2，任何页面都用这一个组件，
       禁止再各自写一套 chips（历史上估值页是下划线红字、别的页是药丸，同一排按钮两种样子）。 -->
  <div class="chips rr" role="group" aria-label="时间区间">
    <span v-for="r in keys" :key="r" class="chip" :class="{ on: range === r }"
          role="button" :aria-pressed="range === r" @click="$emit('update:range', r)">{{ r }}</span>
    <span v-if="periods.length" class="seg2 per" role="group" aria-label="周期">
      <button v-for="p in periods" :key="p" type="button" :class="{ on: period === p }"
              :aria-pressed="period === p" @click="$emit('update:period', p)">{{ p }}</button>
    </span>
  </div>
</template>
<script setup>
import { RANGE_KEYS } from '../utils/series'
defineProps({
  range: { type: String, default: '' },
  keys: { type: Array, default: () => RANGE_KEYS },
  period: { type: String, default: '' },
  periods: { type: Array, default: () => [] },   // 传 ['日线','月线','年线'] 才显示分段
})
defineEmits(['update:range', 'update:period'])
</script>
<style scoped>
/* 卡片内的区间条：去掉 .chips 默认横向内边距，允许换行，周期分段靠右 */
.rr{ padding:0 0 6px; flex-wrap:wrap; align-items:center; }
.per{ margin-left:auto; }
@media (max-width:400px){
  .per{ margin-left:0; width:100%; }
  .per button{ flex:1; }
}
</style>
