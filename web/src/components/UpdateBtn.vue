<template>
  <div class="upd">
    <span class="asof num" v-if="asof && !compact">数据 {{ asof.slice(5).replace('-', '/') }}</span>
    <button class="btn" :class="{ spin: running, labeled: label }" @click="start" :disabled="running" :title="running ? '正在拉取最新行情和净值' : '更新数据'">
      <van-icon name="replay" /><span v-if="label" class="lbl">{{ running ? '更新中' : '更新数据' }}</span>
    </button>
    <span v-if="errors.length && !running" class="err" @click="show = true">{{ errors.length }} 项失败</span>
    <van-popup v-model:show="show" position="bottom" round closeable :style="{ maxHeight: '70vh' }">
      <div class="pop">
        <h4>这几项没拉到</h4>
        <p class="sub">其他数据已更新；失败的沿用上次的数据，过一会儿再点一次更新通常就好</p>
        <div v-for="(e, i) in errors" :key="i" class="eline">{{ e }}</div>
      </div>
    </van-popup>
  </div>
</template>
<script setup>
// 更新数据：后台拉，图标转圈；完了停转、页面数据自动刷新；失败的折成一个小红字，点开看明细
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { showSuccessToast } from 'vant'
import { get, post, dropAll, dataVer } from '../api'
defineProps({ compact: Boolean, label: Boolean })
const asof = ref(''), running = ref(false), errors = ref([]), show = ref(false)
let timer = null

async function poll() {
  const s = await get('/api/update', { fresh: true })
  const was = running.value
  running.value = s.running
  if (s.asof) asof.value = s.asof
  if (s.running) { timer = setTimeout(poll, 1500); return }
  errors.value = s.errors || []
  if (was) {
    dropAll()
    showSuccessToast(errors.value.length ? `已更新，${errors.value.length} 项没拉到` : '数据已是最新')
    dataVer.value++
  }
}
async function start() {
  if (running.value) return
  running.value = true
  await post('/api/update', {})
  timer = setTimeout(poll, 1500)
}
onMounted(poll)
onBeforeUnmount(() => clearTimeout(timer))
</script>
<style scoped>
.upd{ display:flex; align-items:center; gap:6px; font-size:12px; color:var(--muted); }
.btn.labeled{ display:inline-flex; align-items:center; justify-content:center;
  width:auto; min-width:30px; padding:0 11px; gap:6px; border-radius:15px; }
.btn .lbl{ font-size:13px; white-space:nowrap; }
.btn{ width:30px; height:30px; border-radius:15px; border:0; background:rgba(0,0,0,.04); color:var(--sub); display:grid; place-items:center; font-size:16px; cursor:pointer; }
.btn:active{ background:rgba(0,0,0,.08); }
.btn.spin .van-icon{ animation:rot .9s linear infinite; color:var(--brand); }
@keyframes rot{ to{ transform:rotate(360deg) } }
.err{ color:#B45309; background:#FEF3C7; border-radius:9px; padding:0 7px; line-height:18px; cursor:pointer; }
.pop{ padding:18px 18px 28px; }
.pop h4{ margin:0 0 4px; font-size:16px; }
.pop .sub{ margin:0 0 12px; font-size:12.5px; color:var(--muted); }
.eline{ font-size:13px; color:var(--sub); padding:8px 0; border-top:1px solid var(--line); word-break:break-all; }
</style>
