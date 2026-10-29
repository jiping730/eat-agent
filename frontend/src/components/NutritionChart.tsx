import { useId } from 'react';

export function NutritionChart({ data, unit = '千卡' }: { data: { label: string; value: number }[]; unit?: string }) {
  const id = useId();
  const max = Math.max(...data.map((item) => item.value), 1);
  return <figure aria-labelledby={id}><figcaption id={id} className="sr-only">七日饮食热量趋势，单位{unit}</figcaption><div className="flex h-48 items-end gap-2 sm:gap-4" role="img" aria-label={data.map((item) => `${item.label}${item.value}${unit}`).join('，')}><>{data.map((item, index) => <div key={`${item.label}-${index}`} className="flex h-full min-w-0 flex-1 flex-col justify-end gap-2 text-center"><span className="text-xs font-medium muted">{item.value ? Math.round(item.value) : '—'}</span><div className="relative mx-auto h-32 w-full max-w-10 overflow-hidden rounded-t-control bg-stone-100"><div className={`absolute inset-x-0 bottom-0 rounded-t-control ${index === data.length - 1 ? 'bg-apricot' : 'bg-sage/70'}`} style={{ height: item.value ? `${Math.max(8, (item.value / max) * 100)}%` : '0%' }} /></div><span className="truncate text-xs muted">{item.label}</span></div>)}</></div></figure>;
}
