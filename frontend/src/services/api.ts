import type { ApiTokens, Conversation, ExperienceSettings, GrillState, KnowledgeDocument, Message, Profile, ProfileSuggestion, User } from '../types';
import { mockApi, mockStream } from './mock';

const BASE = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.PROD ? '' : '/api');
export const isMockMode = import.meta.env.VITE_USE_MOCK_API === 'true';
const ACCESS_KEY = 'eat.access';
const REFRESH_KEY = 'eat.refresh';

export class ApiError extends Error {
  constructor(message: string, public status = 0, public payload?: unknown) {
    super(message);
    this.name = 'ApiError';
  }
}

export const tokenStore = {
  get access() { return localStorage.getItem(ACCESS_KEY); },
  get refresh() { return localStorage.getItem(REFRESH_KEY); },
  set(tokens: ApiTokens) {
    localStorage.setItem(ACCESS_KEY, tokens.access_token);
    if (tokens.refresh_token) localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  },
  clear() { localStorage.removeItem(ACCESS_KEY); localStorage.removeItem(REFRESH_KEY); },
};

async function parseResponse(response: Response) {
  const text = await response.text();
  if (!text) return null;
  try { return JSON.parse(text); } catch { return text; }
}

function expireSession() {
  tokenStore.clear();
  window.dispatchEvent(new Event('eat:unauthorized'));
}

async function refreshToken() {
  if (!tokenStore.refresh) { expireSession(); throw new ApiError('登录已过期，请重新登录', 401); }
  const response = await fetch(`${BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: tokenStore.refresh }),
  });
  if (!response.ok) { expireSession(); throw new ApiError('登录已过期，请重新登录', 401); }
  const tokens = await parseResponse(response) as ApiTokens;
  tokenStore.set(tokens);
  return tokens.access_token;
}

export async function request<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (tokenStore.access) headers.set('Authorization', `Bearer ${tokenStore.access}`);
  let response: Response;
  try { response = await fetch(`${BASE}${path}`, { ...options, headers }); }
  catch { throw new ApiError('无法连接服务，请检查网络后重试'); }
  if (response.status === 401 && retry && tokenStore.refresh) {
    await refreshToken();
    return request<T>(path, options, false);
  }
  if (!response.ok) {
    const payload = await parseResponse(response);
    if (response.status === 401) expireSession();
    const detail = typeof payload === 'object' && payload && 'detail' in payload ? String(payload.detail) : '';
    const message = typeof payload === 'object' && payload && 'message' in payload ? String(payload.message) : detail;
    const error = typeof payload === 'object' && payload && 'error' in payload ? String(payload.error) : '';
    throw new ApiError(message || error || (response.status === 401 ? '登录已过期，请重新登录' : `请求失败（${response.status}）`), response.status, payload);
  }
  return await parseResponse(response) as T;
}

function normalizeConversation(raw: any): Conversation {
  return { ...raw, id: String(raw.id ?? raw.conversation_id), title: raw.title || '新对话', messages: raw.messages?.map(normalizeMessage) };
}
function normalizeMessage(raw: any): Message {
  const kind = (raw.kind ?? ({ answer: 'advice', confirmation: 'clarification', rejection: 'clarification', safety: 'clarification' } as Record<string, string>)[raw.type] ?? raw.type) as Message['kind'];
  return { ...raw, id: String(raw.id ?? raw.message_id ?? crypto.randomUUID()), content: raw.content ?? raw.answer ?? '', kind };
}
function listData<T>(raw: any): T[] { return Array.isArray(raw) ? raw : raw?.items ?? raw?.data ?? []; }

const activityLabels: Record<string, string> = { sedentary: '久坐', light: '轻度活动', moderate: '中度活动', high: '高度活动' };
const activityValues: Record<string, string> = Object.fromEntries(Object.entries(activityLabels).map(([key, value]) => [value, key]));
const goalLabels: Record<string, string> = { weight_control: '温和减脂', muscle_gain: '增肌', balanced_diet: '均衡饮食', maintain: '保持精力' };
const goalValues: Record<string, string> = Object.fromEntries(Object.entries(goalLabels).map(([key, value]) => [value, key]));

function normalizeUser(raw: any): User {
  const username = raw?.username ?? raw?.email ?? '';
  return { ...raw, id: String(raw?.id ?? ''), username, email: raw?.email ?? username, nickname: raw?.nickname ?? username, roles: raw?.roles ?? [] };
}

function normalizeProfile(raw: any): Profile {
  const source = raw?.profile ?? raw ?? {};
  const consent = Boolean(raw?.consent_granted ?? source.personalization_enabled ?? false);
  return {
    nickname: source.nickname ?? '',
    age: source.age,
    height_cm: source.height_cm,
    weight_kg: source.weight_kg,
    gender: source.gender ?? source.sex,
    activity_level: activityLabels[source.activity_level] ?? source.activity_level,
    goal: goalLabels[source.goal ?? source.health_goal] ?? source.goal,
    health_goal: source.health_goal && goalLabels[source.health_goal] ? goalLabels[source.health_goal] : (source.health_goal ?? ''),
    dietary_preferences: source.dietary_preferences ?? [],
    restrictions: source.restrictions ?? source.disliked_foods ?? [],
    allergies: source.allergies ?? [],
    memory_enabled: consent,
    personalization_enabled: consent,
  };
}

function profilePayload(profile: Profile) {
  return {
    age: profile.age,
    height_cm: profile.height_cm,
    weight_kg: profile.weight_kg,
    sex: profile.gender || undefined,
    activity_level: profile.activity_level ? activityValues[profile.activity_level] ?? profile.activity_level : undefined,
    health_goal: profile.goal ? goalValues[profile.goal] ?? profile.goal : undefined,
    allergies: profile.allergies ?? [],
    dietary_preferences: profile.dietary_preferences ?? [],
    disliked_foods: profile.restrictions ?? [],
    consent_granted: true,
  };
}

function normalizeSuggestion(raw: any): ProfileSuggestion {
  const field = raw.field === 'disliked_foods' ? 'restrictions' : raw.field;
  const value = Array.isArray(raw.value) ? raw.value.join('、') : goalLabels[raw.value] ?? String(raw.value ?? '');
  return { ...raw, field, value } as ProfileSuggestion;
}

function normalizeGrill(raw: any): GrillState | null {
  if (!raw) return null;
  if (raw.status && raw.question && raw.question.options) return raw as GrillState;
  const action = raw.action;
  if (!raw.question && !raw.candidates?.length && action !== 'pending_confirmation') return null;
  const candidates = raw.candidates ?? raw.options ?? [];
  return {
    status: action === 'pending_confirmation' ? 'ready' : 'waiting',
    question: raw.question ? {
      id: String(raw.target_field ?? 'grill-question'),
      field: String(raw.target_field ?? ''),
      question: String(raw.question),
      reason: String(raw.reason ?? '为了让建议更贴合你的情况，我只需要确认这一项。'),
      options: candidates.map((item: any) => ({ label: String(item.label ?? item.value), value: String(item.value ?? item.label) })),
      allow_custom: true,
    } : undefined,
    collected: raw.context?.fields ?? raw.collected ?? {},
    missing: raw.missing_fields ?? raw.missing ?? [],
  };
}

export type StreamHandlers = {
  onToken: (text: string) => void;
  onGrill: (state: GrillState) => void;
  onDone: (message?: Message) => void;
};

async function streamAsk(question: string, conversationId: string | null, signal: AbortSignal, handlers: StreamHandlers) {
  const response = await fetch(`${BASE}/ask/stream`, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...(tokenStore.access ? { Authorization: `Bearer ${tokenStore.access}` } : {}) },
    body: JSON.stringify({ question, message: question, conversation_id: conversationId }),
  });
  if (response.status === 404) {
    const result = await request<any>('/ask', { method: 'POST', body: JSON.stringify({ question, conversation_id: conversationId }), signal });
    const grill = normalizeGrill(result.grill);
    if (grill) handlers.onGrill(grill);
    handlers.onDone(normalizeMessage({ id: crypto.randomUUID(), role: 'assistant', content: result.answer ?? result.content }));
    return;
  }
  if (!response.ok) {
    const payload = await parseResponse(response);
    if (response.status === 401) expireSession();
    throw new ApiError(response.status === 401 ? '登录已过期，请重新登录' : `对话请求失败（${response.status}）`, response.status, payload);
  }
  if (!response.body) throw new ApiError('浏览器无法读取流式响应');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const processEvent = (block: string) => {
    const data = block.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n');
    if (!data || data === '[DONE]') return;
    try {
      const event = JSON.parse(data);
      const type = event.type ?? event.event;
      const payload = event.data && typeof event.data === 'object' ? event.data : event;
      const grillPayload = payload.grill ?? event.grill;
      const normalizedGrill = normalizeGrill(grillPayload ?? (payload.question ? payload : null));
      if (normalizedGrill) handlers.onGrill(normalizedGrill);
      if (type === 'answer.completed' || type === 'done' || type === 'complete') {
        handlers.onDone(normalizeMessage(payload.message ?? payload));
      }
      else if (type === 'error') throw new ApiError(payload.message || event.message || '生成中断，请重试');
      else if (!normalizedGrill) {
        const token = event.delta ?? event.token ?? event.content ?? payload.delta ?? payload.token ?? payload.content ?? (typeof event.data === 'string' ? event.data : '');
        if (token) handlers.onToken(token);
      }
    } catch (error) {
      if (error instanceof ApiError) throw error;
      handlers.onToken(data);
    }
  };
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || '';
    blocks.forEach(processEvent);
    if (done) { if (buffer.trim()) processEvent(buffer); break; }
  }
  handlers.onDone();
}

export const api = {
  async login(username: string, password: string) {
    if (isMockMode) return mockApi.login(username, password);
    const tokens = await request<ApiTokens>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
    tokenStore.set(tokens); return tokens;
  },
  async register(username: string, password: string, nickname: string) {
    if (isMockMode) return mockApi.register(username, password, nickname);
    const result = await request<ApiTokens | User>('/auth/register', { method: 'POST', body: JSON.stringify({ username, password }) });
    if ('access_token' in result) tokenStore.set(result);
    return result;
  },
  async logout() {
    if (isMockMode) return mockApi.logout();
    try { await request('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: tokenStore.refresh }) }); } finally { tokenStore.clear(); }
  },
  me: () => isMockMode ? mockApi.me() : request<any>('/me').then(normalizeUser),
  conversations: async () => {
    if (isMockMode) return mockApi.conversations();
    return listData<any>(await request('/conversations')).map(normalizeConversation);
  },
  conversation: async (id: string) => isMockMode ? mockApi.conversation(id) : normalizeConversation(await request(`/conversations/${id}`)),
  createConversation: async (title = '新对话') => {
    if (isMockMode) return mockApi.createConversation(title);
    return normalizeConversation(await request('/conversations', { method: 'POST', body: JSON.stringify({ title }) }));
  },
  deleteConversation: (id: string) => isMockMode ? mockApi.deleteConversation(id) : request(`/conversations/${id}`, { method: 'DELETE' }),
  archiveConversation: (id: string, archived = true) => isMockMode ? mockApi.archiveConversation(id, archived) : archived ? request(`/conversations/${id}/archive`, { method: 'POST' }) : request(`/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title: '新对话' }) }),
  askStream: (question: string, conversationId: string | null, signal: AbortSignal, handlers: StreamHandlers) =>
    isMockMode ? mockStream(question, conversationId, signal, handlers) : streamAsk(question, conversationId, signal, handlers),
  regenerate: async (conversationId: string) => isMockMode ? mockApi.regenerate(conversationId) : normalizeMessage(await request<any>(`/conversations/${conversationId}/regenerate`, { method: 'POST' })),
  feedback: (messageId: string, feedback: 'up' | 'down') => isMockMode ? mockApi.feedback(messageId, feedback) : request(`/messages/${messageId}/feedback`, { method: 'POST', body: JSON.stringify({ rating: feedback }) }),
  profile: () => isMockMode ? mockApi.profile() : request<any>('/me/profile').then(normalizeProfile),
  updateProfile: (profile: Profile) => isMockMode ? mockApi.updateProfile(profile) : request<any>('/me/profile', { method: 'PUT', body: JSON.stringify(profilePayload(profile)) }).then(normalizeProfile),
  deleteProfile: () => isMockMode ? mockApi.updateProfile({ nickname: '', dietary_preferences: [], restrictions: [], allergies: [], memory_enabled: false, personalization_enabled: false }) : request('/me/profile', { method: 'DELETE' }),
  profileSuggestions: async () => isMockMode ? mockApi.profileSuggestions() : listData<any>(await request('/me/profile/suggestions')).map(normalizeSuggestion),
  documents: async () => isMockMode ? mockApi.documents() : listData<KnowledgeDocument>(await request('/me/knowledge/documents')),
  addDocument: (title: string, content: string) => isMockMode ? mockApi.addDocument(title, content) : request<KnowledgeDocument>('/me/knowledge/documents', { method: 'POST', body: JSON.stringify({ source_name: title, title, content }) }),
  deleteDocument: (id: string) => isMockMode ? mockApi.deleteDocument(id) : request(`/me/knowledge/documents/${id}`, { method: 'DELETE' }),
  experienceSettings: async () => {
    if (isMockMode) return mockApi.experienceSettings();
    const [profile, memory] = await Promise.all([request<any>('/me/profile'), request<any>('/memory')]);
    return { memory_enabled: Boolean(memory?.consent), personalization_enabled: Boolean(profile?.consent_granted) } satisfies ExperienceSettings;
  },
  updateExperienceSettings: async (settings: ExperienceSettings) => {
    if (isMockMode) return mockApi.updateExperienceSettings(settings);
    await Promise.all([
      request('/memory/consent', { method: 'POST', body: JSON.stringify({ granted: settings.memory_enabled }) }),
      request('/me/profile/consent', { method: 'POST', body: JSON.stringify({ granted: settings.personalization_enabled }) }),
    ]);
    return settings;
  },
};
