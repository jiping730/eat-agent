import type { MealPlan } from '../types';

const KEY = 'eat.meal-plans.v1';
const read = (): MealPlan[] => {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { return []; }
};

// 餐食计划来自用户主动保存的 AI 结果，不生成静态推荐内容。
export const mealPlanService = {
  list: async () => read(),
  saveFromMessage: async (content: string) => {
    const plan: MealPlan = {
      id: crypto.randomUUID(), title: 'AI 餐食计划', meal_type: 'dinner',
      reason: '根据本次对话中已确认的目标与偏好生成', content,
      created_at: new Date().toISOString(),
    };
    localStorage.setItem(KEY, JSON.stringify([plan, ...read()])); return plan;
  },
};
