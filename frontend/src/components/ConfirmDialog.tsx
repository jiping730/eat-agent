import { useEffect, useRef } from 'react';
import { Warning } from '@phosphor-icons/react';

export function ConfirmDialog({ open, title, description, confirmLabel = '确认删除', busy = false, onConfirm, onCancel }: { open: boolean; title: string; description: string; confirmLabel?: string; busy?: boolean; onConfirm: () => void; onCancel: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onCancel(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); previous?.focus(); };
  }, [open, busy, onCancel]);
  if (!open) return null;
  return <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/35 p-4 sm:items-center" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onCancel(); }}><div ref={ref} className="card w-full max-w-md p-6 shadow-lift" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-description"><Warning size={28} className="mb-4 text-amber-800" /><h2 id="confirm-title" className="text-xl">{title}</h2><p id="confirm-description" className="mt-3 text-sm leading-6 muted">{description}</p><div className="mt-8 flex justify-end gap-2"><button className="btn btn-ghost" onClick={onCancel} disabled={busy}>保留</button><button className="btn bg-red-800 text-white" onClick={onConfirm} disabled={busy}>{busy ? '正在处理…' : confirmLabel}</button></div></div></div>;
}
