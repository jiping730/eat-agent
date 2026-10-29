import { PencilSimple, Trash } from '@phosphor-icons/react';
import type { MealRecord } from '../../types';

export function MealRecordCard({ record, onEdit, onDelete }: { record: MealRecord; onEdit: () => void; onDelete: () => void }) {
  const confidenceLabel = record.calorie_confidence === 'high' ? '较有把握' : record.calorie_confidence === 'low' ? '参考性较低' : '中等把握';
  const calorieText = record.calorie_status === 'estimating'
    ? '正在估算…'
    : record.calories != null
      ? `约 ${record.calories} 千卡`
      : '暂未估算热量';
  return <article className="flex items-start gap-3 bg-paper py-4"><div className="min-w-0 flex-1"><h4 className="font-semibold">{record.food_name}</h4>{record.note && <p className="mt-1 line-clamp-2 text-sm leading-6 muted">{record.note}</p>}<p className="mt-1 text-xs subtle">{record.source === 'chat' ? '来自 AI 对话' : '手动记录'} · 本机保存</p>{record.calorie_assumptions?.length ? <p className="mt-1 text-xs subtle">估算依据：{record.calorie_assumptions.join('；')}</p> : null}</div><div className="shrink-0 text-right"><p className="text-sm font-semibold">{calorieText}</p>{record.calorie_status === 'estimated' && <p className="mt-1 text-xs text-sage">AI 估算 · {confidenceLabel}</p>}{record.calorie_status === 'unavailable' && <p className="mt-1 text-xs subtle">可编辑后重试</p>}<div className="mt-1 flex justify-end"><button className="icon-btn size-9" aria-label={`编辑${record.food_name}`} onClick={onEdit}><PencilSimple size={17} /></button><button className="icon-btn size-9" aria-label={`删除${record.food_name}`} onClick={onDelete}><Trash size={17} /></button></div></div></article>;
}
