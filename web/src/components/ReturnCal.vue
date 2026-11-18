<template>
  <!-- 收益日历：全站**唯一**一份格子实现（账户基金详情 / 市场基金详情 / 收益明细 三处共用）。
       页头（标题、月份翻页、日周月年、¥/%）留在各页，因为控件组合本来就不一样；
       但「周一起头的 7 列 / 3 列 / 4 列格子 + 涨跌底色 + 选中环 + 买卖小圆点」只有这一份。 -->
  <div class="ret-cal">
    <div class="wk" v-if="mode === '日'"><span v-for="w in WD" :key="w">{{ w }}</span></div>
    <div class="grid" :class="gridCls">
      <div v-for="(c, k) in cells" :key="c && c.key != null ? c.key : 'e' + k" class="cell"
           :class="[c ? cellCls(c) : '', { big: mode !== '日', sel: !!c && !!sel && c.key === sel, pt: clickable && canPick(c) }]"
           @click="pick(c)">
        <template v-if="c">
          <!-- 买卖记号：实心 = 买入、空心 = 卖出/清仓（图例在调用方，没成交的日子不显示） -->
          <span v-if="c.act" class="dot" :class="actCls(c.act)" :title="c.act"></span>
          <span class="dd">{{ mode === '日' ? c.d : c.label }}</span>
          <span class="dv num">{{ fmt(c) }}</span>
          <span v-if="subFmt" class="dsub num" :class="tone(c.p)">{{ subFmt(c) }}</span>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { tone } from '../fmt'

const props = defineProps({
  // 日 = 7 列格子（一格一天）；周 = 4 列；月 / 年 = 3 列。桌面（≥900）周/月/年统一 6 列
  mode: { type: String, default: '日' },
  // 日模式：{ d: 日期号, key: 'YYYY-MM-DD', v: 收益数值, p: 收益率, state: '待更新', act: '买入' }
  // 周/月/年：{ key, label: '2026年10月', v, p, state?, act? }；空位直接给 null
  cells: { type: Array, default: () => [] },
  // 主数值怎么显示（各页口径不同：¥ 还是 %，缺数据写 '' 还是 '—'），由调用方决定
  fmt: { type: Function, required: true },
  // 可选的第二行小字（账户基金详情在周/月/年下要同时看收益额和收益率）
  subFmt: { type: Function, default: null },
  // 选中的格子 key
  sel: { type: String, default: '' },
  // 能不能点：市场基金详情只是看图，不接点击
  clickable: { type: Boolean, default: false },
})
const emit = defineEmits(['select'])

const WD = '一二三四五六日'
const gridCls = computed(() => (props.mode === '日' ? 'g7' : props.mode === '周' ? 'g4' : 'g3'))
const cellCls = c => (c.v == null ? (c.state ? 'none' : 'nodata') : c.v > 0 ? 'pos' : c.v < 0 ? 'neg' : 'flat')
// 有数值，或者「待更新」这种占位状态，才允许点开看明细 —— 空格子点了没东西
const canPick = c => !!c && (c.v != null || !!c.state)
const actCls = a => (String(a || '').includes('买') ? 'buy' : 'sell')
const pick = c => {
  if (props.clickable && canPick(c)) emit('select', c)
}
</script>

<style scoped>
.wk{ display:grid; grid-template-columns:repeat(7,1fr); margin:0 0 4px;
  font-size:11px; color:var(--muted); text-align:center; }
.grid{ display:grid; gap:4px; min-width:0; }
.grid.g7{ grid-template-columns:repeat(7,minmax(0,1fr)); }
/* 周 / 月 / 年统一 3 列：4 列时一格只有 79px，「2026年第47周」放不下只能省略成
   「2026年第4…」（2026-11-18 用户就吐槽过这个）。必须 minmax(0,1fr)：1fr 的最小宽度是
   auto，长文字会把那列单独撑到 101px，几列就不等宽了（实测 73.6/74.3/74.1/101.3）。 */
.grid.g4, .grid.g3{ grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; }
.cell{ position:relative; min-width:0; min-height:46px; border-radius:8px; background:transparent;
  display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px;
  border:1.5px solid transparent; }
.cell.big{ min-height:58px; }
.cell.pt{ cursor:pointer; }
/* 有日期但那天没有净值：压淡底色，别让空格子铺满后抢走有收益那几天的注意力 */
.cell.nodata{ background:#FCFCFD; }
.cell.flat{ background:#F4F6F9; }
.cell.pos{ background:#FDECEC; } .cell.pos .dv{ color:var(--up); }
.cell.neg{ background:#E7F6EC; } .cell.neg .dv{ color:var(--down); }
.cell.sel{ border-color:var(--brand); }
.cell .dd{ max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  font-size:11.5px; color:var(--sub); }
.cell .dv{ font-size:11px; font-weight:600; }
.cell .dsub{ font-size:10px; color:var(--muted); }
/* 大格子的期间名（「2026年第47周」）几乎占满宽度，右上角的买卖圆点会压到最后一个字；
   左右各留 9px 内沟，圆点落在这条沟里，文字照旧居中 */
.cell.big .dd{ padding:0 6px; box-sizing:border-box; font-size:12.5px; }
.cell.big .dv{ font-size:13px; }
.cell.big .dsub{ font-size:10.5px; }
/* 买卖记号：5px 时实心/空心在手机上分不出来，给到 6px、描边 1.8px */
.cell .dot{ position:absolute; top:5px; right:5px; width:6px; height:6px;
  border-radius:50%; background:var(--brand); }
/* 大格子：期间名几乎占满整行，圆点放右上角会压住最后一个字；挪到右下角 ——
   下面那行「+0.04%」是居中的，右下的角落本来就空着 */
.cell.big .dot{ top:auto; bottom:6px; right:7px; }
.cell .dot.sell{ background:transparent; box-shadow:inset 0 0 0 1.8px var(--brand); }
/* 桌面卡片宽：格子被拉宽后同步加高、放大字号，否则变成一排扁横条；
   日 7 列不变，周/月/年统一 6 列（4 列在 936 宽下会拉成 221×66） */
@media (min-width:900px){
  .wk{ margin:2px 0 6px; font-size:12px; }
  .grid.g7{ gap:8px; }
  .grid.g4, .grid.g3{ grid-template-columns:repeat(6,minmax(0,1fr)); gap:8px; }
  .cell{ min-height:78px; border-radius:10px; gap:4px; }
  .cell.big{ min-height:88px; }
  .cell .dd{ font-size:13px; }
  .cell .dv{ font-size:14px; }
  .cell .dsub{ font-size:11px; }
  .cell.big .dd{ font-size:14px; }
  .cell.big .dv{ font-size:16px; }
  .cell.big .dsub{ font-size:11.5px; }
}
</style>
