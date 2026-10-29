import type { Conversation, ExperienceSettings, GrillState, KnowledgeDocument, NutritionEstimate, NutritionEstimateInput, Profile, User } from '../types';
import type { StreamHandlers } from './api';

// 独立开发适配器：只有 VITE_USE_MOCK_API=true 才会被调用，不用于生产兜底。
const wait = (ms = 350) => new Promise((resolve) => setTimeout(resolve, ms));
const user: User = { id: 'preview-user', email: 'preview@eat.local', nickname: '济平' };
let profile: Profile = { nickname: '济平', age: 25, goal: '保持精力', activity_level: '轻度活动', dietary_preferences: ['清淡'], restrictions: [], allergies: [], memory_enabled: true, personalization_enabled: true };
let settings: ExperienceSettings = { memory_enabled: true, personalization_enabled: true };
let conversations: Conversation[] = [];
let documents: KnowledgeDocument[] = [];
const grillAnswers = new Map<string, string>();

export const mockApi = {
  login: async (_email: string, _password: string) => { await wait(); return { access_token: 'preview-token' }; },
  register: async (_email: string, _password: string, nickname: string) => { await wait(); profile.nickname = nickname; user.nickname = nickname; return { access_token: 'preview-token' }; },
  logout: async () => { await wait(100); },
  me: async () => { await wait(200); return user; },
  conversations: async () => { await wait(); return conversations.filter((item) => !item.archived); },
  conversation: async (id: string) => { await wait(); const item = conversations.find((entry) => entry.id === id); if (!item) throw new Error('对话不存在'); return item; },
  createConversation: async (title: string) => { await wait(150); const item: Conversation = { id: crypto.randomUUID(), title, messages: [] }; conversations.unshift(item); return item; },
  deleteConversation: async (id: string) => { conversations = conversations.filter((item) => item.id !== id); },
  archiveConversation: async (id: string, archived: boolean) => { const item = conversations.find((entry) => entry.id === id); if (item) item.archived = archived; },
  grillAction: async (_id: string, action: { question_id: string; value: string }) => { grillAnswers.set(action.question_id, action.value); return { grill: { status: 'ready', collected: { 饮食忌口: action.value }, missing: [] } satisfies GrillState, message: undefined }; },
  regenerate: async (_conversationId: string) => ({ id: crypto.randomUUID(), role: 'assistant' as const, content: '我们可以把目标拆得小一些：先保证规律三餐，再记录一周饮食，观察自己的饱腹感和精力变化。' }),
  feedback: async (_messageId: string, _feedback: 'up' | 'down') => ({}),
  profile: async () => { await wait(); return profile; },
  updateProfile: async (value: Profile) => { await wait(); profile = value; return profile; },
  profileSuggestions: async () => [],
  documents: async () => { await wait(); return documents; },
  addDocument: async (title: string, content: string) => { await wait(); const doc: KnowledgeDocument = { id: crypto.randomUUID(), title, content, status: 'indexing', created_at: new Date().toISOString() }; documents.unshift(doc); setTimeout(() => { doc.status = 'ready'; }, 1200); return doc; },
  deleteDocument: async (id: string) => { documents = documents.filter((doc) => doc.id !== id); },
  estimateNutrition: async (input: NutritionEstimateInput): Promise<NutritionEstimate> => {
    await wait(700);
    return {
      calories: 420,
      protein_g: 18,
      carbs_g: 58,
      fat_g: 12,
      confidence: 'medium',
      assumptions: [input.note?.trim() || '按常见一份估算，具体份量和做法会影响结果'],
      source: 'ai',
      status: 'estimated',
      message: '热量为 AI 根据食物描述和常见份量估算的近似值',
    };
  },
  experienceSettings: async () => settings,
  updateExperienceSettings: async (value: ExperienceSettings) => { settings = value; profile = { ...profile, ...value }; return settings; },
};

function answerFor(question: string): { text: string; grill?: GrillState } {
  if (/减肥|减脂/.test(question) && !/餐|计划|安排/.test(question)) {
    return { text: '减脂更适合从能长期坚持的小改变开始。你可以先关注三点：\n\n1. 三餐尽量规律，不必极端节食。\n2. 每餐保留蛋白质和蔬菜，主食按饱腹感适量调整。\n3. 用一周记录观察变化，再决定下一步。\n\n这些是通用生活方式建议。如果你愿意，我可以先帮你确认一个适合自己的阶段目标；只有你明确提出需要时，我们再制定具体餐食计划。' };
  }
  if (/安排|制定|计划/.test(question) && /餐|食谱/.test(question) && !grillAnswers.has('restrictions')) {
    return { text: '', grill: { status: 'waiting', question: { id: 'restrictions', field: 'restrictions', question: '这顿饭有需要避开的食材吗？', reason: '为了避免推荐你不吃或不能吃的食材，我只需要先确认这一项。', options: [{ label: '没有忌口', value: '没有忌口' }, { label: '不吃海鲜', value: '不吃海鲜' }, { label: '素食', value: '素食' }], allow_custom: true }, collected: {}, missing: ['restrictions'] } };
  }
  if (/热量|卡路里/.test(question)) return { text: `${question.replace(/[？?]/g, '')}的热量会受份量与烹饪方式影响。以常见可食部估算时，还需要知道你大概吃了多少，例如“一小碗”或“150 克”。你可以补充份量，我再给你更接近实际范围的估算。` };
  if (grillAnswers.has('restrictions')) return { text: `已按你的偏好整理一份晚餐建议：\n\n- 主食：杂粮饭一小碗\n- 蛋白质：清蒸鱼或北豆腐一份\n- 蔬菜：两种时蔬，约一大盘\n\n这份方案已避开：${grillAnswers.get('restrictions')}。份量仍需结合你的食量和当天其他餐次调整，热量与营养均为估算，不作为医疗建议。` };
  return { text: '可以从今天的真实饮食开始聊起。比如告诉我你吃了什么、大概份量，或者你目前最想改善的一点。我会先理解你的需求，信息不足时只问最必要的一项。' };
}

export async function mockStream(question: string, conversationId: string | null, signal: AbortSignal, handlers: StreamHandlers) {
  let conversation = conversations.find((item) => item.id === conversationId);
  if (!conversation) { conversation = { id: crypto.randomUUID(), title: question.slice(0, 18), messages: [] }; conversations.unshift(conversation); }
  conversation.messages = [...(conversation.messages || []), { id: crypto.randomUUID(), role: 'user', content: question }];
  await wait(500);
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  const result = answerFor(question);
  if (result.grill) { handlers.onGrill(result.grill); handlers.onDone(); return; }
  for (const char of result.text) {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    handlers.onToken(char);
    await new Promise((resolve) => setTimeout(resolve, 12));
  }
  conversation.messages.push({ id: crypto.randomUUID(), role: 'assistant', content: result.text });
  handlers.onDone();
}
