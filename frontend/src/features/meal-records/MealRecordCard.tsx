import { PencilSimple, Trash } from '@phosphor-icons/react';
import type { MealRecord } from '../../types';

export function MealRecordCard({ record, onEdit, onDelete }: { record: MealRecord; onEdit: () => void; onDelete: () => void }) {
  return <article className="flex items-start gap-3 bg-paper py-4"><div className="min-w-0 flex-1"><h4 className="font-semibold">{record.food_name}</h4>{record.note && <p className="mt-1 line-clamp-2 text-sm leading-6 muted">{record.note}</p>}<p className="mt-1 text-xs subtle">{record.source === 'chat' ? '来自 AI 对话' : '手动记录'} · 本机保存</p></div><div className="shrink-0 text-right"><p className="text-sm font-semibold">{record.calories != null ? `约 ${record.calories} 千卡` : '未估算热量'}</p><div className="mt-1 flex justify-end"><button className="icon-btn size-9" aria-label={`编辑${record.food_name}`} onClick={onEdit}><PencilSimple size={17} /></button><button className="icon-btn size-9" aria-label={`删除${record.food_name}`} onClick={onDelete}><Trash size={17} /></button></div></div></article>;
}
