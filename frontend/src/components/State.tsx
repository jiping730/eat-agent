import type { ReactNode } from 'react';
import { ArrowClockwise, CheckCircle, Info, WarningCircle } from '@phosphor-icons/react';

export function LoadingState({ label = '正在加载' }: { label?: string }) {
  return <div className="flex min-h-44 flex-col items-center justify-center gap-4" role="status"><div className="skeleton h-3 w-28" /><div className="skeleton h-3 w-40" /><span className="sr-only">{label}</span></div>;
}
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div className="card card-pad flex flex-col items-start gap-4 border-l-4 border-l-red-700" role="alert"><WarningCircle size={24} className="text-red-800" /><div><h3 className="font-semibold">暂时没能加载</h3><p className="mt-1 text-sm muted">{message}</p></div>{onRetry && <button className="btn btn-outline" onClick={onRetry}><ArrowClockwise size={18} />重新加载</button>}</div>;
}
export function EmptyState({ icon, title, description, action }: { icon?: ReactNode; title: string; description: string; action?: ReactNode }) {
  return <div className="flex min-h-52 flex-col items-center justify-center px-6 py-10 text-center"><div className="mb-4 flex size-12 items-center justify-center rounded-full bg-mint text-sage">{icon ?? <Info size={24} />}</div><h3 className="text-lg font-semibold">{title}</h3><p className="mt-2 max-w-md text-sm leading-6 muted">{description}</p>{action && <div className="mt-6">{action}</div>}</div>;
}
export function Badge({ children, tone = 'green' }: { children: ReactNode; tone?: 'green' | 'orange' | 'neutral' | 'red' }) {
  const colors = { green: 'bg-mint text-sage', orange: 'bg-orange-50 text-amber-800', neutral: 'bg-stone-100 text-stone-700', red: 'bg-red-50 text-red-800' };
  return <span className={`badge ${colors[tone]}`}>{children}</span>;
}
export function InlineNotice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'success' }) {
  return <div className={`flex items-start gap-2 rounded-control p-3 text-sm leading-6 ${tone === 'success' ? 'bg-mint text-sage' : 'bg-orange-50 text-amber-900'}`}>{tone === 'success' ? <CheckCircle className="mt-1 shrink-0" size={18} /> : <Info className="mt-1 shrink-0" size={18} />}<div>{children}</div></div>;
}
