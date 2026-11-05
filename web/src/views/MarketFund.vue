<template>
  <div class="page no-tab">
    <SubBar :title="d ? d.name : '基金走势'" :fallback="`/a/${aid}/market/funds`" />
    <div class="wrap narrow">
      <van-loading v-if="!d && !err" style="margin:40px 0" vertical>拉取净值…（第一次查要几秒）</van-loading>
      <p v-else-if="err" class="empty-tip">{{ err }}</p>
      <template v-else>
        <div class="card head">
          <div class="sub">{{ code }} · {{ d.msg }}</div>
          <div class="g">
            <div><span>最新净值</span><b class="num">{{ last.toFixed(4) }}</b><small class="num">{{ d.dates[d.dates.length - 1].replace(/-/g, '/') }}</small></div>
            <div><span>{{ range }}收益</span><b class="num" :class="tone(ret)">{{ pct(ret) }}</b></div>
            <div><span>{{ range }}最大回撤</span><b class="num down">{{ mdd.toFixed(2) }}%</b></div>
          </div>
        </div>
        <div class="card">
          <div class="chips rr"><span v-for="r in ranges" :key="r.k" class="chip" :class="{ on: range === r.k }" @click="range = r.k">{{ r.k }}</span></div>
          <LineChart :dates="seg.dates" :values="seg.values" :height="240" unit=""
                     :fmt-tip="i => `${seg.dates[i]}<br/>净值 <b>${seg.values[i].toFixed(4)}</b>`" />
        </div>
      </template>
    </div>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { get } from '../api'
import { pct, tone } from '../fmt'
import SubBar from '../components/SubBar.vue'
import LineChart from '../components/LineChart.vue'
const route = useRoute()
const aid = route.params.aid, code = route.params.code
const d = ref(null), err = ref('')
get(`/api/market/fund/${code}`).then(x => {
  d.value = x
  const rc = JSON.parse(localStorage.getItem('aw-recent-funds') || '[]').filter(r => r.code !== code)
  localStorage.setItem('aw-recent-funds', JSON.stringify([{ code, name: x.name }, ...rc].slice(0, 12)))
}).catch(e => { err.value = e.message })
const ranges = [{ k: '近1月', m: 1 }, { k: '近3月', m: 3 }, { k: '近1年', m: 12 }, { k: '近3年', m: 36 }, { k: '近5年', m: 60 }, { k: '全部', m: 0 }]
const range = ref('近1年')
const seg = computed(() => {
  const n = d.value
  const m = ranges.find(r => r.k === range.value).m
  if (!m) return n
  const end = new Date(n.dates[n.dates.length - 1]); end.setMonth(end.getMonth() - m)
  const i = Math.max(0, n.dates.findIndex(x => x >= end.toISOString().slice(0, 10)))
  return { dates: n.dates.slice(i), values: n.values.slice(i) }
})
const last = computed(() => d.value.values[d.value.values.length - 1])
const ret = computed(() => { const v = seg.value.values; return (v[v.length - 1] / v[0] - 1) * 100 })
const mdd = computed(() => { let pk = -Infinity, m = 0; for (const v of seg.value.values) { pk = Math.max(pk, v); m = Math.min(m, v / pk - 1) } return m * 100 })
</script>
<style scoped>
.narrow{ max-width:960px !important; }
.head .sub{ font-size:12px; color:var(--muted); }
.g{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:10px; }
.g span{ display:block; font-size:12px; color:var(--muted); } .g b{ display:block; font-size:18px; margin-top:3px; } .g small{ font-size:11px; color:var(--muted); }
.rr{ padding:0 0 6px; }
.k{ font-size:11.5px; color:var(--muted); margin:6px 0 0; }
</style>
