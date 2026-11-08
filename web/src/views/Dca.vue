<template>
  <div class="page no-tab">
    <SubBar title="新钱怎么分" :fallback="`/a/${aid}/calc`" />
    <div class="wrap">
      <div class="card inp">
        <div class="k">这次要投入（元）</div>
        <div class="amt"><span>¥</span><input v-model="amount" type="number" inputmode="decimal" placeholder="0" /></div>
        <div class="chips q"><span v-for="v in [5000, 10000, 20000, 50000]" :key="v" class="chip" :class="{ on: +amount === v }" @click="amount = String(v)">{{ v / 10000 >= 1 ? v / 10000 + ' 万' : v }}</span></div>
      </div>
      <template v-if="d && +amount > 0">
        <div class="sum">
          <div><span>能买进</span><b class="num">¥{{ money(d.buy, 0) }}</b></div>
          <div><span>剩下</span><b class="num">¥{{ money(+amount - d.buy, 0) }}</b></div>
          <div><span>投完总额</span><b class="num">¥{{ money(d.after, 0) }}</b></div>
        </div>
        <p class="hint" v-if="d.lost > 1">有 ¥{{ money(d.lost, 0) }} 因为不够一手买不进，这次先不投，下次一起买</p>
        <div class="sec-t"><span>每只买多少 · 按目标比例</span><span>金额</span></div>
        <van-cell-group inset>
          <van-cell v-for="r in d.rows" :key="r.code">
            <template #title>
              <div class="rn">{{ r.name }}</div>
              <div class="rs">{{ r.slot }} · 目标 {{ r.w_tgt.toFixed(1) }}%<template v-if="r.slot_n > 1"> · 位置内 {{ r.x.toFixed(0) }}%</template></div>
              <div class="rs warn" v-if="r.note">{{ r.note }}</div>
            </template>
            <template #value>
              <div class="num rv" :class="{ zero: !r.amount }">¥{{ money(r.amount, 0) }}</div>
              <div class="num rs" v-if="r.qty">{{ money(r.qty, r.otc ? 2 : 0) }} {{ r.unit }}</div>
              <van-button v-if="r.amount" size="mini" round plain type="primary" class="rb"
                          :to="{ path: `/a/${aid}/record`, query: { code: r.code, side: '买入', amount: r.amount } }">记一笔</van-button>
            </template>
          </van-cell>
        </van-cell-group>
        <p class="hint">新钱优先补「低于目标」的位置；场内按整手，场外按金额。投完再看一眼「调仓」页有没有新的偏离</p>
      </template>
      <p v-else class="empty-tip">输入这次要投的金额，按目标比例算出每只该买多少</p>
    </div>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get } from '../api'
import { money } from '../fmt'
import SubBar from '../components/SubBar.vue'
const aid = useRoute().params.aid
const amount = ref(localStorage.getItem('aw-dca') || '')
const d = ref(null)
let t = null
watch(amount, v => {
  clearTimeout(t)
  if (!(+v > 0)) { d.value = null; return }
  localStorage.setItem('aw-dca', v)
  t = setTimeout(async () => { d.value = await get(`/api/acct/${aid}/dca?amount=${+v}`) }, 250)
}, { immediate: true })
</script>
<style scoped>
.inp{ padding:16px 18px 12px; }
.k{ font-size:12.5px; color:var(--muted); }
.amt{ display:flex; align-items:baseline; gap:6px; border-bottom:1px solid var(--line); padding:6px 0 8px; }
.amt span{ font-size:24px; font-weight:600; }
.amt input{ flex:1; border:0; outline:0; font-size:32px; font-weight:700; width:100%; background:transparent; font-variant-numeric:tabular-nums; }
.q{ padding:12px 0 0; }
/* 三格汇总：等分列 + 每格居中（与首页资产卡同一套，见 CLAUDE.md「KPI 行对齐」） */
.sum{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:12px 12px 0; background:#fff; border-radius:14px; padding:12px 14px; }
.sum > div{ min-width:0; text-align:center; }
.sum span{ display:block; font-size:12px; color:var(--muted); } .sum b{ display:block; font-size:16px; margin-top:4px; }
.hint{ font-size:12px; color:var(--muted); margin:8px 18px 0; line-height:1.6; }
.rn{ font-size:14.5px; font-weight:500; } .rs{ font-size:12px; color:var(--muted); margin-top:2px; }
.rs.warn{ color:#B45309; }
.rv{ color:var(--up); font-weight:650; font-size:15px; } .rv.zero{ color:var(--muted); font-weight:400; }
.rb{ margin-top:4px; }
</style>
