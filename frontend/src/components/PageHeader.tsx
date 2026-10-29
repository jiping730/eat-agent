import type { ReactNode } from 'react';

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: ReactNode }) {
  return <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div>{eyebrow && <p className="mb-2 text-xs font-semibold uppercase tracking-[.16em] text-sage">{eyebrow}</p>}<h1 className="text-[28px] font-bold sm:text-4xl">{title}</h1>{description && <p className="mt-3 max-w-2xl text-sm leading-6 muted sm:text-base">{description}</p>}</div>{action && <div className="shrink-0">{action}</div>}</header>;
}
