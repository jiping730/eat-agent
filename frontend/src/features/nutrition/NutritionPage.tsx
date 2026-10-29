import { useNavigate } from 'react-router-dom';
import { ArrowRight, ChartLineUp, ChatCircleText, Info, Notebook } from '@phosphor-icons/react';
import { mealRecordService } from '../../services/mealRecords';
import { useAsync } from '../../hooks/useAsync';
import { lastDays, toDateKey } from '../../lib/date';
import { PageHeader } from '../../components/PageHeader';
import { LoadingState, ErrorState, EmptyState, InlineNotice } from '../../components/State';
import { NutritionSummaryCard } from '../../components/NutritionSummaryCard';
import { NutritionChart } from '../../components/NutritionChart';

export function NutritionPage() {
  const navigate = useNavigate();
  const days = lastDays(7);
  const { data: records, loading, error, retry } = useAsync(() => mealRecordService.listRange(days[0], toDateKey()), []);
  if (loading) return <div className="page"><LoadingState /></div>;
  if (error) return <div className="page"><ErrorState message={error} onRetry={() => void retry()} /></div>;
  const items = records || [];
  const today = items.filter((item) => item.date === toDateKey());
  const calories = today.reduce((sum, item) => sum + (item.calories || 0), 0);
  const trend = days.map((day) => ({ label: new Intl.DateTimeFormat('zh-CN', { weekday: 'short' }).format(new Date(`${day}T12:00:00`)).replace('周', ''), value: items.filter((item) => item.date === day).reduce((sum, item) => sum + (item.calories || 0), 0) }));
  const recordedDays = trend.filter((item) => item.value > 0).length;
  const macros = [{ key: 'protein_g', label: '蛋白质', unit: '克' }, { key: 'carbs_g', label: '碳水化合物', unit: '克' }, { key: 'fat_g', label: '脂肪', unit: '克' }] as const;
  const macroData = macros.map((macro) => ({ ...macro, value: today.reduce((sum, item) => sum + (item[macro.key] || 0), 0), available: today.some((item) => item[macro.key] != null) }));
  const askAnalysis = () => navigate(`/chat?prompt=${encodeURIComponent(`请根据我本周已记录的 ${items.length} 条饮食信息，给我一段温和、简短的饮食习惯解读。不要给医疗诊断，也不要编造我没有记录的营养数据。`)}`);
  return <div className="page"><PageHeader eyebrow="看见趋势，而非评判" title="营养看板" description="这里只汇总你保存过的记录。缺失的数据不会被自动补齐。" />{!items.length ? <div className="card"><EmptyState icon={<ChartLineUp size={27} weight="light" />} title="暂无足够记录" description="先记下几餐，再看趋势。单天的数字不需要代表你的全部饮食。" action={<button className="btn btn-primary" onClick={() => navigate('/records')}><Notebook size={18} />去记第一餐</button>} /></div> : <><div className="grid gap-6 lg:grid-cols-[1fr_1.6fr]"><NutritionSummaryCard calories={calories} /><section className="card card-pad"><div className="mb-6"><h2 className="font-sans text-lg font-semibold">近七天热量趋势</h2><p className="mt-1 text-xs muted">仅显示含热量估算的记录</p></div><NutritionChart data={trend} /></section></div><div className="mt-6 grid gap-6 md:grid-cols-2"><section className="card card-pad"><h2 className="font-sans text-lg font-semibold">今日餐次分布</h2><div className="mt-5 space-y-3">{[['breakfast', '早餐'], ['lunch', '午餐'], ['dinner', '晚餐'], ['snack', '加餐']].map(([key, label]) => { const list = today.filter((item) => item.meal_type === key); return <div key={key} className="flex items-center justify-between border-b pb-3 last:border-0" style={{ borderColor: 'var(--border-subtle)' }}><span className="text-sm muted">{label}</span><span className="text-sm font-medium">{list.length ? `${list.length} 条 · 约 ${list.reduce((sum, item) => sum + (item.calories || 0), 0)} 千卡` : '未记录'}</span></div>; })}</div></section><section className="card card-pad"><h2 className="font-sans text-lg font-semibold">宏量营养素摘要</h2><div className="mt-5 space-y-4">{macroData.map((macro) => <div key={macro.key} className="flex items-center justify-between"><span className="text-sm muted">{macro.label}</span><span className="text-sm font-semibold">{macro.available ? `约 ${Math.round(macro.value)} ${macro.unit}` : '暂无数据'}</span></div>)}</div><p className="mt-5 text-xs leading-5 subtle">只有记录中明确填写的营养数据才参与汇总。</p></section></div><section className="card mt-6 border-l-4 border-l-sage p-5 sm:p-6"><p className="text-xs font-semibold tracking-wider text-sage">轻松食解读</p><h2 className="mt-2 font-sans text-lg font-semibold">这一周有 {recordedDays} 天留下了热量记录</h2><p className="mt-2 text-sm leading-7 muted">{recordedDays < 3 ? '目前记录还比较少，不适合判断长期趋势。先保持自然记录，不需要为了看板完整而改变正常饮食。' : '已经有几天的记录可供回顾。建议更关注餐次规律与整体搭配，不必追求每天热量完全一致。'}</p><button className="btn btn-secondary mt-4" onClick={askAnalysis}><ChatCircleText size={18} />让 AI 结合记录继续解读<ArrowRight size={16} /></button></section></>}<div className="mt-6 space-y-3"><InlineNotice>这些数字来自你的手动记录或对话保存，均为估算值，不用于医学诊断。</InlineNotice><p className="flex items-start gap-2 text-xs leading-5 subtle"><Info size={16} className="mt-0.5 shrink-0" />数据来源：本机饮食记录。服务端饮食记录接口尚未接入。</p></div></div>;
}
