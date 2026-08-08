// Mock routes.js for testing
export default [
  {
    path: '/home',
    title: '工作台',
    icon: 'home',
    component: 'home/Dashboard',
    auth: 'home.dashboard.view'
  },
  {
    path: '/system/account',
    title: '账户管理',
    icon: 'user',
    component: 'system/account/Index',
    auth: 'system.account.view'
  },
  {
    path: '/system/role',
    title: '角色管理',
    icon: 'team',
    component: 'system/role/Index',
    auth: 'system.role.view'
  },
  {
    path: '/system/setting',
    title: '系统设置',
    icon: 'setting',
    component: 'system/setting/Index',
    auth: 'system.setting.view'
  },
  {
    path: '/no-auth-page',
    title: '无权限页面',
    component: 'noauth/Index'
    // No auth field - should be flagged
  }
]
