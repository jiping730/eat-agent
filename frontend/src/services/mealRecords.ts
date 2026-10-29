import type { MealRecord } from '../types';

const KEY = 'eat.meal-records.v1';
const read = (): MealRecord[] => {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { return []; }
};
const write = (records: MealRecord[]) => localStorage.setItem(KEY, JSON.stringify(records));

// TODO(API pending): 服务端提供独立饮食记录接口后，仅替换此 service，页面无需改动。
export const mealRecordService = {
  persistence: 'local' as const,
  list: async (date?: string) => read().filter((record) => !date || record.date === date),
  listRange: async (from: string, to: string) => read().filter((record) => record.date >= from && record.date <= to),
  create: async (input: Omit<MealRecord, 'id'>) => {
    const record = { ...input, id: crypto.randomUUID() };
    write([...read(), record]); return record;
  },
  update: async (id: string, input: Partial<MealRecord>) => {
    const records = read(); const index = records.findIndex((record) => record.id === id);
    if (index < 0) throw new Error('没有找到这条记录');
    records[index] = { ...records[index], ...input }; write(records); return records[index];
  },
  remove: async (id: string) => write(read().filter((record) => record.id !== id)),
};
