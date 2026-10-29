import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { BookOpenText, ChartDonut, ChatCircleText, CookingPot, House, Leaf, Notebook, UserCircle } from '@phosphor-icons/react';
import { isMockMode } from '../services/api';

const nav = [
  { to: '/', label: '首页', icon: House },
  { to: '/chat', label: 'AI 助手', icon: ChatCircleText },
  { to: '/records', label: '饮食记录', icon: Notebook },
  { to: '/nutrition', label: '营养看板', icon: ChartDonut },
  { to: '/profile', label: '我的', icon: UserCircle },
];
function Brand() {
  return <NavLink to="/" className="flex items-center gap-3" aria-label="轻松食首页"><span className="flex size-10 items-center justify-center rounded-full bg-sage text-paper"><Leaf size={23} weight="light" /></span><span><strong className="block font-display text-xl tracking-tight">轻松食</strong><span className="block text-xs leading-5 subtle">Eat Agent</span></span></NavLink>;
}
function MobileBottomNav() {
  return <nav className="fixed inset-x-0 bottom-0 z-40 border-t bg-paper/95 px-2 pb-[max(8px,env(safe-area-inset-bottom))] pt-2 lg:hidden" style={{ borderColor: 'var(--border-subtle)' }} aria-label="主要导航"><div className="mx-auto grid max-w-lg grid-cols-5">{nav.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-control text-[11px] font-medium transition ${isActive ? 'bg-mint text-sage' : 'text-stone-500'}`}><Icon size={22} weight="light" /><span>{label}</span></NavLink>)}</div></nav>;
}
function DesktopSidebar() {
  const location = useLocation();
  return <aside className="fixed inset-y-0 left-0 z-40 hidden w-[232px] flex-col border-r bg-paper px-5 py-7 lg:flex" style={{ borderColor: 'var(--border-subtle)' }}><Brand /><nav className="mt-12 flex flex-col gap-2" aria-label="主要导航">{nav.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `flex min-h-12 items-center gap-3 rounded-control px-3 text-sm font-medium transition ${isActive ? 'bg-mint text-sage' : 'text-stone-600 hover:bg-stone-50'}`}><Icon size={21} weight="light" />{label}</NavLink>)}<NavLink to="/recipes" className={`flex min-h-12 items-center gap-3 rounded-control px-3 text-sm font-medium transition ${location.pathname === '/recipes' ? 'bg-mint text-sage' : 'text-stone-600 hover:bg-stone-50'}`}><CookingPot size={21} weight="light" />餐食推荐</NavLink></nav><div className="mt-auto rounded-card bg-[#f2eee3] p-4"><BookOpenText size={22} className="mb-3 text-sage" weight="light" /><p className="text-sm font-semibold">你的饮食笔记</p><p className="mt-1 text-xs leading-5 muted">把交流过的建议留成自己的参考。</p><NavLink to="/knowledge" className="mt-3 inline-flex text-sm font-semibold text-sage underline decoration-sage/30 underline-offset-4">个人知识库</NavLink></div></aside>;
}
export function AppShell() {
  return <div className="min-h-screen"><DesktopSidebar /><div className="min-h-screen lg:pl-[232px]"><header className="flex items-center justify-between px-4 py-4 lg:hidden"><Brand />{isMockMode && <span className="badge bg-orange-50 text-amber-900">开发预览</span>}</header><Outlet /></div><MobileBottomNav /></div>;
}
