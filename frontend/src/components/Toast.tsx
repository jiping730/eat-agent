import { CheckCircle, WarningCircle } from '@phosphor-icons/react';
import { useApp } from '../app/AppContext';

export function ToastHost() {
  const { toasts } = useApp();
  return <div className="pointer-events-none fixed inset-x-4 bottom-24 z-[60] flex flex-col items-center gap-2 lg:bottom-6" aria-live="polite">{toasts.map((toast) => <div key={toast.id} className={`flex items-center gap-2 rounded-control px-4 py-3 text-sm text-white shadow-lift ${toast.tone === 'success' ? 'bg-sage' : 'bg-red-800'}`} style={{ animation: 'toast-in 220ms ease-out' }}>{toast.tone === 'success' ? <CheckCircle size={20} /> : <WarningCircle size={20} />}{toast.message}</div>)}</div>;
}
