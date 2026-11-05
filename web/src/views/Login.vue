<template>
  <div class="page no-tab login">
    <div class="box">
      <img src="/icon.svg" alt="" />
      <h2>全天候再平衡</h2>
      <p>这个页面设了访问密码</p>
      <van-field v-model="pw" type="password" placeholder="输入密码" class="in" @keyup.enter="go" autofocus />
      <van-button round block type="primary" :loading="busy" @click="go">进入</van-button>
    </div>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showFailToast } from 'vant'
import { post, dropAll } from '../api'
const route = useRoute(), router = useRouter()
const pw = ref(''), busy = ref(false)
async function go() {
  if (!pw.value) return
  busy.value = true
  try {
    await post('/api/login', { password: pw.value })
    dropAll()
    router.replace(route.query.to || '/')
  } catch (e) { showFailToast(e.message) } finally { busy.value = false }
}
</script>
<style scoped>
.login{ display:grid; place-items:center; }
.box{ width:min(340px, 86vw); text-align:center; margin-top:-8vh; }
.box img{ width:64px; height:64px; }
.box h2{ margin:12px 0 4px; font-size:22px; }
.box p{ color:var(--muted); font-size:13px; margin:0 0 22px; }
.in{ border-radius:12px; margin-bottom:14px; }
</style>
