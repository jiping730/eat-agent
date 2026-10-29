export const toDateKey = (date = new Date()) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};
export const shiftDate = (key: string, days: number) => {
  const date = new Date(`${key}T12:00:00`); date.setDate(date.getDate() + days); return toDateKey(date);
};
export const formatDate = (key: string) => new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' }).format(new Date(`${key}T12:00:00`));
export const lastDays = (count: number, end = toDateKey()) => Array.from({ length: count }, (_, index) => shiftDate(end, index - count + 1));
export const greeting = () => { const hour = new Date().getHours(); return hour < 11 ? '早上好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好'; };
