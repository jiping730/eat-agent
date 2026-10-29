import { useNavigate } from 'react-router-dom';
import { CookingPot, SlidersHorizontal, ArrowRight } from '@phosphor-icons/react';
import { useAsync } from '../../hooks/useAsync';
import { mealPlanService } from '../../services/mealPlans';
import { api } from '../../services/api';
import { PageHeader } from '../../components/PageHeader';
import { LoadingState, ErrorState, EmptyState, Badge, InlineNotice } from '../../components/State';

export function RecipesPage() {
  const navigate = useNavigate();
  const { data, loading, error, retry } = useAsync(async () => { const [plans, profile] = await Promise.allSettled([mealPlanService.list(), api.profile()]); return { plans: plans.status === 'fulfilled' ? plans.value : [], profile: profile.status === 'fulfilled' ? profile.value : null }; }, []);
  if (loading) return <div className="page"><LoadingState /></div>;
  if (error || !data) return <div className="page"><ErrorState message={error || '推荐加载失败'} onRetry={() => void retry()} /></div>;
  const { plans, profile } = data;
  const preferences = [...(profile?.dietary_preferences || []), ...(profile?.restrictions || []), ...(profile?.allergies || []).map((item) => `过敏：${item}`)];
  const ask = (prompt: string) => navigate(`/chat?prompt=${encodeURIComponent(prompt)}`);
  return <div className="page page-narrow"><PageHeader eyebrow="Meal planner" title="餐食推荐" description="建议从你的生活目标出发；只有你确认后，AI 才生成具体餐食计划。" /><section className="card card-pad mb-8"><div className="flex flex-wrap items-center gap-2"><Badge>{profile?.goal || '尚未设置目标'}</Badge>{preferences.map((item) => <Badge key={item} tone="neutral">{item}</Badge>)}{!preferences.length && <span className="text-sm muted">暂未填写饮食偏好、忌口或过敏信息</span>}</div><button className="btn btn-ghost mt-3 px-0" onClick={() => navigate('/profile')}><SlidersHorizontal size={18} />查看会影响推荐的资料<ArrowRight size={16} /></button></section>{plans.length ? <section><div className="section-title"><div><h2>已生成的餐食计划</h2><p className="mt-1 text-sm muted">来自你确认并保存的 AI 对话</p></div></div><div className="space-y-4">{plans.map((plan) => <article key={plan.id} className="card card-pad"><div className="flex flex-wrap items-center gap-2"><Badge tone="orange">已生成计划</Badge><span className="text-xs subtle">{new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric' }).format(new Date(plan.created_at))}</span></div><h3 className="mt-4 text-lg font-semibold">{plan.title}</h3><p className="mt-2 text-sm muted">{plan.reason}</p><div className="prose-chat mt-4 border-t pt-4" style={{ borderColor: 'var(--border-subtle)' }}>{plan.content}</div>{(plan.calories || plan.protein_g) && <p className="mt-4 text-sm muted">约 {plan.calories || '—'} 千卡 · 蛋白质 {plan.protein_g || '—'} 克</p>}<button className="btn btn-outline mt-5" onClick={() => ask(`请调整这份餐食计划：\n${plan.content}`)}>调整这份计划</button></article>)}</div></section> : <div className="card"><EmptyState icon={<CookingPot size={28} weight="light" />} title="还没有生成餐食计划" description="你可以先聊聊目标与口味。信息足够并确认后，再生成适合自己的方案。" action={<div className="flex flex-col gap-2 sm:flex-row"><button className="btn btn-primary" onClick={() => ask('我想开始制定餐食计划，请先看看还需要哪些必要信息。')}>开始制定计划</button><button className="btn btn-secondary" onClick={() => ask('我想告诉你我的饮食偏好，先不生成餐单。')}>告诉 AI 我的偏好</button></div>} /></div>}<div className="mt-6"><InlineNotice>“通用建议”与“已生成计划”会分开显示。推荐不构成医疗效果承诺，特殊健康状况请咨询专业人士。</InlineNotice></div></div>;
}
