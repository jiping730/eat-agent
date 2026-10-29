import { useNavigate } from 'react-router-dom';
import { ArrowRight, BookOpenText, ChatCircleText, ForkKnife, Leaf, MagnifyingGlass, Notebook, Plant, Target } from '@phosphor-icons/react';
import { useApp } from '../../app/AppContext';
import { useAsync } from '../../hooks/useAsync';
import { api } from '../../services/api';
import { mealRecordService } from '../../services/mealRecords';
import { toDateKey, greeting } from '../../lib/date';
import { LoadingState, EmptyState, InlineNotice, Badge } from '../../components/State';
import { QuickActionCard } from '../../components/QuickActionCard';
import { NutritionSummaryCard } from '../../components/NutritionSummaryCard';
import type { Conversation, KnowledgeDocument, Profile } from '../../types';

const actions = [
  { title: '查询食物热量', description: '了解份量与烹饪方式的影响', prompt: '帮我查一下鸡胸肉的热量', icon: MagnifyingGlass },
  { title: '获取减脂建议', description: '先聊目标，不急着生成餐单', prompt: '我想减脂，可以先给我一些通用建议吗？', icon: Plant },
  { title: '制定餐食计划', description: '确认必要信息后再开始规划', prompt: '我想制定一份餐食计划', icon: Notebook },
  { title: '分析一顿饭', description: '从吃了什么和大概份量开始', prompt: '帮我分析一下今天这顿饭', icon: ForkKnife },
];
const suggestions = ['一顿饭吃多少蛋白质比较合适？', '外食时怎样搭配更均衡？', '燕麦和面包的早餐怎么选？'];

export function HomePage() {
  const { user } = useApp();
  const navigate = useNavigate();
  const { data, loading, retry } = useAsync(async () => {
    const [profile, conversations, documents, records] = await Promise.allSettled([api.profile(), api.conversations(), api.documents(), mealRecordService.list(toDateKey())]);
    return {
      profile: profile.status === 'fulfilled' ? profile.value : null,
      conversations: conversations.status === 'fulfilled' ? conversations.value : [],
      documents: documents.status === 'fulfilled' ? documents.value : null,
      records: records.status === 'fulfilled' ? records.value : [],
      partialError: [profile, conversations, documents].some((item) => item.status === 'rejected'),
    };
  }, []);
  if (loading) return <div className="page"><LoadingState /></div>;
  const result = data || { profile: null, conversations: [], documents: null, records: [], partialError: true };
  const profile = result.profile as Profile | null;
  const conversations = result.conversations as Conversation[];
  const documents = result.documents as KnowledgeDocument[] | null;
  const calories = result.records.reduce((sum, item) => sum + (item.calories || 0), 0);
  const completed = profile ? ['age', 'height_cm', 'weight_kg', 'goal', 'activity_level'].filter((key) => Boolean(profile[key as keyof Profile])).length : 0;
  const completion = Math.round((completed / 5) * 100);
  const ask = (prompt: string) => navigate(`/chat?prompt=${encodeURIComponent(prompt)}`);
  return <div className="page"><header className="mb-8"><p className="mb-2 text-sm font-medium text-sage">{greeting()}，{profile?.nickname || user?.nickname || '朋友'}</p><h1 className="max-w-2xl text-[30px] sm:text-4xl">今天，吃顿舒服的饭。</h1><p className="mt-3 text-sm leading-6 muted">不追求完美饮食，先看见自己的真实习惯。</p></header>{result.partialError && <div className="mb-6"><InlineNotice>部分个人数据暂时不可用。你仍可使用饮食记录或发起对话。<button className="ml-1 font-semibold underline underline-offset-4" onClick={() => void retry()}>重新加载</button></InlineNotice></div>}<div className="grid gap-6 lg:grid-cols-[1.45fr_1fr]"><section className="relative overflow-hidden rounded-card bg-sage p-6 text-paper shadow-soft sm:p-8"><div className="relative z-10 max-w-lg"><Badge><Leaf size={14} />陪伴式健康建议</Badge><h2 className="mt-6 text-2xl sm:text-3xl">有疑问，先和轻松食聊聊</h2><p className="mt-3 text-sm leading-7 text-white/80">从食物热量到一餐搭配，我会根据你提供的信息回答；不够了解时，只追问最必要的一项。</p><button className="btn mt-6 bg-paper text-sage hover:bg-white" onClick={() => navigate('/chat')}><ChatCircleText size={19} />开始新对话<ArrowRight size={17} /></button></div><Leaf className="absolute -bottom-8 -right-5 rotate-[-18deg] text-white/10" size={170} weight="light" /></section><NutritionSummaryCard calories={calories} label="今日饮食记录" /></div><section className="mt-10"><div className="section-title"><div><h2>想从哪里开始？</h2><p className="mt-1 text-sm muted">选择一个方向，也可以直接说出自己的问题</p></div></div><div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">{actions.map((action) => <QuickActionCard key={action.title} {...action} icon={<action.icon size={22} weight="light" />} onClick={() => ask(action.prompt)} />)}</div></section><div className="mt-10 grid gap-8 lg:grid-cols-[1.35fr_1fr]"><div><section><div className="section-title"><h2>最近对话</h2>{conversations.length > 0 && <button className="text-sm font-semibold text-sage" onClick={() => navigate('/chat')}>查看全部</button>}</div><div className="card">{conversations.length ? conversations.slice(0, 3).map((conversation) => <button key={conversation.id} className="flex w-full items-center gap-3 border-b p-4 text-left last:border-0 hover:bg-stone-50" style={{ borderColor: 'var(--border-subtle)' }} onClick={() => navigate(`/chat/${conversation.id}`)}><ChatCircleText size={20} className="shrink-0 text-sage" weight="light" /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold">{conversation.title}</span><span className="mt-1 block text-xs subtle">继续上次的交流</span></span><ArrowRight size={17} className="text-stone-400" /></button>) : <EmptyState icon={<ChatCircleText size={24} />} title="还没有对话" description="你的第一次交流会出现在这里。" action={<button className="btn btn-secondary" onClick={() => navigate('/chat')}>问第一个问题</button>} />}</div></section><section className="mt-8"><h2 className="mb-4 text-xl">也可以这样问</h2><div className="flex flex-wrap gap-2">{suggestions.map((item) => <button key={item} className="min-h-11 rounded-full border bg-paper px-4 text-left text-sm text-stone-700 transition hover:border-sage hover:text-sage" style={{ borderColor: 'var(--border-subtle)' }} onClick={() => ask(item)}>{item}</button>)}</div></section></div><aside className="space-y-4"><section className="card card-pad"><div className="flex items-center justify-between"><span className="flex size-10 items-center justify-center rounded-full bg-mint text-sage"><Target size={21} weight="light" /></span><span className="text-sm font-semibold text-sage">{completion}%</span></div><h3 className="mt-4 font-semibold">健康档案</h3><p className="mt-2 text-sm leading-6 muted">{completion === 100 ? '基础资料已完善，你可以随时调整。' : '补充基础信息后，建议会更贴近你的日常。'}</p><div className="mt-4 h-2 rounded-full bg-stone-100"><div className="h-full rounded-full bg-sage" style={{ width: `${completion}%` }} /></div><button className="btn btn-ghost mt-3 w-full" onClick={() => navigate('/profile')}>{completion ? '查看健康档案' : '完善健康档案'}<ArrowRight size={16} /></button></section><section className="card card-pad"><BookOpenText size={23} className="text-sage" weight="light" /><h3 className="mt-4 font-semibold">个人知识库</h3><p className="mt-2 text-sm leading-6 muted">{documents === null ? '状态暂时无法读取，可稍后重试。' : documents.length ? `${documents.length} 份个人文档，其中 ${documents.filter((doc) => doc.status === 'ready').length} 份可检索。` : '放入自己的饮食笔记，需要时随时查找。'}</p><button className="btn btn-ghost mt-3 w-full" onClick={() => navigate('/knowledge')}>管理我的文档<ArrowRight size={16} /></button></section></aside></div></div>;
}
