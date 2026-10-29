import type { ReactNode } from 'react';

export function QuickActionCard({ icon, title, description, onClick }: { icon: ReactNode; title: string; description: string; onClick: () => void }) {
  return <button className="card group flex min-h-36 flex-col items-start p-4 text-left transition duration-200 hover:-translate-y-0.5 hover:shadow-lift sm:p-5" onClick={onClick}><span className="mb-5 flex size-10 items-center justify-center rounded-full bg-mint text-sage">{icon}</span><span className="font-semibold">{title}</span><span className="mt-1 text-xs leading-5 muted">{description}</span><span className="mt-auto pt-3 text-sm font-semibold text-sage transition group-hover:translate-x-1">开始聊聊 →</span></button>;
}
