import { useState, type FormEvent } from 'react';
import { CalendarBlank, CaretLeft, CaretRight, Notebook, Plus, X } from '@phosphor-icons/react';
import { mealRecordService } from '../../services/mealRecords';
import { useAsync } from '../../hooks/useAsync';
import { useApp } from '../../app/AppContext';
import { formatDate, lastDays, shiftDate, toDateKey } from '../../lib/date';
import type { MealRecord, MealType } from '../../types';
import { PageHeader } from '../../components/PageHeader';
import { EmptyState, ErrorState, LoadingState, Badge } from '../../components/State';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { MealRecordCard } from './MealRecordCard';

const mealLabels: Record<MealType, string> = { breakfast: '早餐', lunch: '午餐', dinner: '晚餐', snack: '加餐' };
const emptyForm = { meal_type: 'breakfast' as MealType, food_name: '', calories: '', note: '' };
export function MealRecordsPage() {
  const { toast } = useApp();
  const [date, setDate] = useState(toDateKey());
  const { data: records, loading, error, retry } = useAsync(() => mealRecordService.list(date), [date]);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<MealRecord | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [deleteRecord, setDeleteRecord] = useState<MealRecord | null>(null);
  const openCreate = (type: MealType = 'breakfast') => { setEditing(null); setForm({ ...emptyForm, meal_type: type }); setFormOpen(true); };
  const openEdit = (record: MealRecord) => { setEditing(record); setForm({ meal_type: record.meal_type, food_name: record.food_name, calories: record.calories?.toString() || '', note: record.note || '' }); setFormOpen(true); };
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true);
    try {
      const value = { date, meal_type: form.meal_type, food_name: form.food_name.trim(), calories: form.calories ? Number(form.calories) : undefined, note: form.note.trim(), source: 'manual' as const };
      if (editing) await mealRecordService.update(editing.id, value); else await mealRecordService.create(value);
      setFormOpen(false); await retry(); toast(editing ? '记录已更新' : '已保存到本机饮食记录');
    } catch (reason) { toast(reason instanceof Error ? reason.message : '保存失败', 'error'); }
    finally { setBusy(false); }
  };
  const remove = async () => { if (!deleteRecord) return; await mealRecordService.remove(deleteRecord.id); setDeleteRecord(null); await retry(); toast('饮食记录已删除'); };
  return <div className="page page-narrow"><PageHeader eyebrow="饮食笔记" title="饮食记录" description="记下真实吃过的食物，不必为了数字完整而勉强估算。" action={<button className="btn btn-primary" onClick={() => openCreate()}><Plus size={18} />记一餐</button>} /><div className="mb-4"><Badge tone="orange">当前仅保存在本机</Badge><p className="mt-2 text-xs leading-5 subtle">服务端饮食记录接口待接入，不会显示为已同步。</p></div><section className="card mb-8 p-3"><div className="flex items-center justify-between"><button className="icon-btn" aria-label="前一天" onClick={() => setDate(shiftDate(date, -1))}><CaretLeft size={20} /></button><div className="text-center"><p className="font-semibold">{formatDate(date)}</p>{date === toDateKey() && <p className="text-xs text-sage">今天</p>}</div><button className="icon-btn" aria-label="后一天" disabled={date >= toDateKey()} onClick={() => setDate(shiftDate(date, 1))}><CaretRight size={20} /></button></div><div className="mt-3 grid grid-cols-7 gap-1">{lastDays(7, date).map((day) => <button key={day} className={`min-h-10 rounded-control text-xs ${day === date ? 'bg-sage text-white' : 'hover:bg-mint'}`} onClick={() => setDate(day)} aria-label={`切换到${day}`}><span className="block">{new Intl.DateTimeFormat('zh-CN', { weekday: 'short' }).format(new Date(`${day}T12:00:00`)).replace('周', '')}</span><span className="font-semibold">{Number(day.slice(-2))}</span></button>)}</div></section>{loading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={() => void retry()} /> : records?.length ? <div className="space-y-6">{(Object.keys(mealLabels) as MealType[]).map((type) => { const items = records.filter((record) => record.meal_type === type); if (!items.length) return null; return <section key={type}><div className="mb-2 flex items-center justify-between"><h2 className="font-sans text-lg font-semibold">{mealLabels[type]}</h2><button className="btn btn-ghost min-h-9 px-2 text-xs" onClick={() => openCreate(type)}><Plus size={15} />补充</button></div><div className="card divide-y px-4" style={{ borderColor: 'var(--border-subtle)' }}>{items.map((record) => <MealRecordCard key={record.id} record={record} onEdit={() => openEdit(record)} onDelete={() => setDeleteRecord(record)} />)}</div></section>; })}</div> : <div className="card"><EmptyState icon={<CalendarBlank size={26} weight="light" />} title="这一天还没有记录" description="从印象最深的一餐开始就好，热量可以留空。" action={<button className="btn btn-secondary" onClick={() => openCreate()}><Notebook size={18} />记下第一餐</button>} /></div>}{formOpen && <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/35 p-0 sm:items-center sm:p-4"><form className="max-h-[92dvh] w-full max-w-lg overflow-y-auto rounded-t-card bg-paper p-6 shadow-lift sm:rounded-card" onSubmit={submit}><div className="mb-6 flex items-center justify-between"><h2 className="text-2xl">{editing ? '编辑饮食记录' : '记下一餐'}</h2><button type="button" className="icon-btn" aria-label="关闭表单" onClick={() => setFormOpen(false)}><X size={22} /></button></div><div className="space-y-5"><label className="field">餐次<select className="input" value={form.meal_type} onChange={(e) => setForm({ ...form, meal_type: e.target.value as MealType })}>{Object.entries(mealLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="field">吃了什么<input className="input" required value={form.food_name} onChange={(e) => setForm({ ...form, food_name: e.target.value })} placeholder="例如：番茄鸡蛋面，一小碗" /></label><label className="field">估算热量（可选）<div className="relative"><input className="input pr-16" type="number" min="0" max="10000" value={form.calories} onChange={(e) => setForm({ ...form, calories: e.target.value })} placeholder="不确定可留空" /><span className="absolute right-3 top-2.5 text-sm muted">千卡</span></div></label><label className="field">备注<textarea className="input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="份量、做法或吃完后的感受" /></label></div><button className="btn btn-primary mt-8 w-full" disabled={busy || !form.food_name.trim()}>{busy ? '正在保存…' : editing ? '保存修改' : '保存这条记录'}</button></form></div>}<ConfirmDialog open={Boolean(deleteRecord)} title="删除这条饮食记录？" description={`“${deleteRecord?.food_name || ''}”将从本机记录中移除，此操作无法撤销。`} onCancel={() => setDeleteRecord(null)} onConfirm={() => void remove()} /></div>;
}
