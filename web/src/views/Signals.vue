<template>
  <div class="page no-tab">
    <SubBar title="策略信号" :fallback="`/a/${aid}/market`" />
    <div class="wrap">
      <van-skeleton v-if="!d" title :row="8" style="padding:16px" />
      <div v-else class="cols2 even">
        <div>
          <div class="card">
            <div class="ct"><b>趋势过滤</b><span class="k num">截至 {{ d.asof.replace(/-/g, '/') }}</span></div>
            <p class="k">价格跌破均线 → 这个资产的目标权重清零，钱按同桶分给别的资产；涨回均线上方再恢复</p>
            <div class="mx">
              <div class="mh"><span></span><span v-for="s in d.strategies" :key="s.key">{{ s.name.replace('V3-B ', '') }}</span></div>
              <div v-for="r in d.rows" :key="r.name" class="mr">
                <div class="mn"><i :class="r.on ? 'on' : 'off'"></i><div><b>{{ r.name }}</b><small>{{ r.desc }} · {{ r.on ? '生效中' : '未触发' }}</small></div></div>
                <span v-for="s in d.strategies" :key="s.key" class="mc">
                  <template v-if="r.applies[s.key]"><van-tag :type="r.on ? 'warning' : 'default'" round>{{ r.on ? '→ 0' : '看着' }}</van-tag></template>
                  <template v-else><em>不用</em></template>
                </span>
              </div>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="ct"><b>三个策略 · 区间涨跌</b><span class="k">基准 {{ (axis[baseIdx] || '').replace(/-/g, '/') }} = 0%，含趋势过滤</span></div>
          <!-- 与全站同一套区间控件（原来这页固定只给近半年，没有区间可选） -->
          <RangeBar :range="range" :period="period" :periods="periods"
                    @update:range="setRange" @update:period="setPeriod" />
          <MultiLine :series="curvesChg" :height="260" :window="win" :reset-key="resetKey" group="signals" />
        </div>
        <van-collapse v-model="showW" class="wts">
          <van-collapse-item name="w" title="三个策略今天的目标权重（公共信息）">
            <div class="wt" v-if="w">
              <div class="wh"><span>资产</span><span v-for="s in w.strategies" :key="s.key">{{ s.name.replace('V3-B ', '') }}</span></div>
              <div v-for="r in w.rows" :key="r.asset" class="wr">
                <div class="wn"><b>{{ r.name }}</b><small :class="{ miss: !r.mine }">{{ r.mine || '同桶分配' }}</small></div>
                <span v-for="s in w.strategies" :key="s.key" class="wv num">{{ r.w[s.key] == null ? '—' : r.w[s.key].toFixed(1) + '%' }}</span>
              </div>
            </div>
          </van-collapse-item>
        </van-collapse>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, peek, dataVer } from '../api'
import SubBar from '../components/SubBar.vue'
import MultiLine from '../components/MultiLine.vue'
import RangeBar from '../components/RangeBar.vue'
import { aggregateSeries, unionDates, windowForRange, rangeStartIndex, rebaseSeries } from '../utils/series'
const aid = useRoute().params.aid
const url = '/api/market/signals'
const d = ref(peek(url) || null)
const w = ref(peek('/api/acct/' + aid + '/weights') || null)
get('/api/acct/' + aid + '/weights').then(x => { w.value = x })
const showW = ref([])
const load = async (fresh = false) => { d.value = await get(url, { fresh }) }
load(); watch(dataVer, () => load(true))

// 统一区间：默认近6月（这页过去就是「近半年」，行为不变但可切换了）
const periods = ['日线', '月线', '年线']
const range = ref('近6月'), period = ref('日线'), bump = ref(0)
const curvesAgg = computed(() => aggregateSeries(d.value?.curves || {}, period.value))
const axis = computed(() => unionDates(curvesAgg.value))
const baseIdx = computed(() => rangeStartIndex(axis.value, range.value))
// 同回测页：以区间基准日为 0%，选区间才看得出谁涨得猛
const curvesChg = computed(() => rebaseSeries(curvesAgg.value, axis.value, baseIdx.value))
const win = computed(() => windowForRange(axis.value, range.value))
const resetKey = computed(() => `${range.value}|${period.value}|${bump.value}`)
const setRange = r => { if (range.value === r) bump.value++; else range.value = r }
const setPeriod = p => { if (period.value === p) bump.value++; else period.value = p }
</script>
<style scoped>
.ct{ display:flex; justify-content:space-between; align-items:baseline; font-size:15px; margin-bottom:6px; }
.k{ font-size:12px; color:var(--muted); line-height:1.6; margin:0; }
.mx{ margin-top:10px; }
.mh, .mr{ display:grid; grid-template-columns:1fr 64px 64px 64px; align-items:center; gap:4px; }
@media (max-width:480px){
  .mh, .mr{ grid-template-columns:repeat(3,1fr); }
  .mh span:first-child{ display:none; }
  .mr .mn{ grid-column:1 / -1; margin-bottom:6px; }
}
.mh{ font-size:11.5px; color:var(--muted); text-align:center; padding-bottom:6px; border-bottom:1px solid var(--line); }
.mr{ padding:10px 0; border-bottom:1px solid var(--line); }
.mr:last-child{ border-bottom:0; }
.mn{ display:flex; gap:8px; align-items:flex-start; min-width:0; }
.mn i{ width:8px; height:8px; border-radius:4px; margin-top:6px; flex:0 0 auto; }
.mn i.on{ background:#F59E0B; } .mn i.off{ background:#CBD5E1; }
.mn b{ display:block; font-size:13.5px; font-weight:550; } .mn small{ font-size:11.5px; color:var(--muted); }
.mc{ text-align:center; } .mc em{ font-style:normal; font-size:11.5px; color:#CBD5E1; }

.wts{ margin:16px 12px 0; border-radius:12px; overflow:hidden; }
.wts :deep(.van-collapse-item__content){ padding:8px 12px; }
.wt{ font-size:13px; }
.wh, .wr{ display:grid; grid-template-columns:1fr 62px 62px 62px; gap:4px; align-items:center; }
.wh{ font-size:11.5px; color:var(--muted); padding:4px 0 8px; border-bottom:1px solid var(--line); text-align:right; }
.wh span:first-child{ text-align:left; }
.wr{ padding:8px 0; border-bottom:1px solid var(--line); } .wr:last-child{ border-bottom:0; }
.wn b{ display:block; font-size:13.5px; font-weight:550; } .wn small{ font-size:11px; color:var(--muted); }
.wn small.miss{ color:#B45309; }
.wv{ text-align:right; color:var(--sub); }
@media (max-width:480px){
  .wh, .wr{ grid-template-columns:repeat(3,1fr); }
  .wh span:first-child{ display:none; }
  .wr .wn{ grid-column:1/-1; display:flex; gap:8px; align-items:baseline; }
  .wh, .wv{ text-align:center !important; }
}

.wts{ margin:16px 12px 0; border-radius:12px; overflow:hidden; }
.wts :deep(.van-collapse-item__content){ padding:8px 12px; }
.wt{ font-size:13px; }
.wh, .wr{ display:grid; grid-template-columns:1fr 62px 62px 62px; gap:4px; align-items:center; }
.wh{ font-size:11.5px; color:var(--muted); padding:4px 0 8px; border-bottom:1px solid var(--line); text-align:right; }
.wh span:first-child{ text-align:left; }
.wr{ padding:8px 0; border-bottom:1px solid var(--line); } .wr:last-child{ border-bottom:0; }
.wn b{ display:block; font-size:13.5px; font-weight:550; } .wn small{ font-size:11px; color:var(--muted); }
.wn small.miss{ color:#B45309; }
.wv{ text-align:right; color:var(--sub); }
@media (max-width:480px){
  .wh, .wr{ grid-template-columns:repeat(3,1fr); }
  .wh span:first-child{ display:none; }
  .wr .wn{ grid-column:1/-1; display:flex; gap:8px; align-items:baseline; }
  .wh, .wv{ text-align:center !important; }
}
</style>
