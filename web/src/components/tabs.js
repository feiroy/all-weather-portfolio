// 四个一级页签（手机底部 / 电脑顶部共用）
export const tabsOf = aid => [
  { k: 'home', label: '资产', icon: 'balance-o', to: `/a/${aid}` },
  { k: 'calc', label: '调仓', icon: 'exchange', to: `/a/${aid}/calc` },
  { k: 'trades', label: '记录', icon: 'orders-o', to: `/a/${aid}/trades` },
  { k: 'market', label: '研究', icon: 'chart-trending-o', to: `/a/${aid}/market` },
]
