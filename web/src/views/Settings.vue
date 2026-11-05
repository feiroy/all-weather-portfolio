<template>
  <div class="page no-tab">
    <SubBar title="账户设置" :fallback="`/a/${aid}`" />
    <div class="wrap narrow">
      <van-skeleton v-if="!a" :row="5" style="padding:16px" />
      <template v-else>
        <van-cell-group inset class="mt">
          <van-field v-model="name" label="账户名" maxlength="20" :label-width="72" placeholder="起个名字">
            <template #button><van-button size="small" type="primary" round :disabled="!name.trim() || name === a.name" @click="save({ name: name.trim() })">保存</van-button></template>
          </van-field>
          <van-cell title="跟随策略" :value="a.strategy_name" is-link :to="`/a/${aid}/weights`" />
          <van-cell title="建立日期" :value="a.created?.replace(/-/g, '/')" />
          <van-cell title="交易记录" :value="`${a.n_trades} 笔`" is-link :to="`/a/${aid}/trades`" />
        </van-cell-group>
        <van-cell-group inset class="mt">
          <van-cell title="切换账户" icon="exchange" is-link to="/" />
        </van-cell-group>
        <van-cell-group inset class="mt">
          <van-cell title="删除这个账户" icon="delete-o" class="danger" clickable @click="remove" />
        </van-cell-group>
        <p class="empty-tip">实盘 / 模拟只在新建账户时选，它是列表里的一个标签，不影响计算。<br>
          删除会先放进回收站（账户列表最下面），可以恢复；最后一个账户不能删</p>
      </template>
    </div>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showSuccessToast, showFailToast } from 'vant'
import { get, patch, del } from '../api'
import SubBar from '../components/SubBar.vue'
const route = useRoute(), router = useRouter()
const aid = route.params.aid
const a = ref(null), name = ref('')
const load = async () => {
  const l = await get('/api/accounts', { fresh: true })
  a.value = l.accounts.find(x => x.id === aid)
  if (!a.value) return router.replace('/')
  name.value = a.value.name
}
load()
async function save(b) {
  try { await patch(`/api/acct/${aid}`, b); showSuccessToast('已保存'); load() } catch (e) { showFailToast(e.message) }
}
async function remove() {
  try { await showConfirmDialog({ title: `删除「${a.value.name}」？`, message: '放进回收站，交易记录和选基配置都保留，随时可以恢复', confirmButtonColor: '#E23B3B', confirmButtonText: '删除' }) } catch { return }
  try { await del(`/api/acct/${aid}`); showSuccessToast('已移到回收站'); router.replace('/') } catch (e) { showFailToast(e.message) }
}
</script>
<style scoped>
.narrow{ max-width:560px !important; }
.mt{ margin-top:12px !important; }
.danger{ color:var(--up); } .danger :deep(.van-icon){ color:var(--up); }
</style>
