import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowUp, ChatCircleText, ClockCounterClockwise, Leaf, Plus, Stop, WarningCircle, X } from '@phosphor-icons/react';
import { api } from '../../services/api';
import { useAsync } from '../../hooks/useAsync';
import { useApp } from '../../app/AppContext';
import type { GrillState, Message, MessageKind } from '../../types';
import { ConversationList } from './ConversationList';
import { ChatMessage } from './ChatMessage';
import { StreamingMessage } from './StreamingMessage';
import { GrillQuestionCard } from './GrillQuestionCard';
import { EmptyState, InlineNotice, LoadingState } from '../../components/State';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { mealRecordService } from '../../services/mealRecords';
import { mealPlanService } from '../../services/mealPlans';
import { toDateKey } from '../../lib/date';

function inferKind(question: string, answer: string): MessageKind {
  if (/餐单|计划|晚餐建议|主食：/.test(answer)) return 'meal_plan';
  if (/热量|千卡|卡路里/.test(question + answer)) return 'calorie';
  if (/需要|补充|多少|确认/.test(answer) && answer.length < 180) return 'clarification';
  return 'advice';
}

export function ChatPage() {
  const { conversationId: routeId } = useParams();
  const [searchParams] = useSearchParams();
  const [initialPrompt] = useState(searchParams.get('prompt') || '');
  const navigate = useNavigate();
  const { toast } = useApp();
  const history = useAsync(() => api.conversations(), []);
  const [currentId, setCurrentId] = useState<string | null>(routeId || null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState('');
  const [generating, setGenerating] = useState(false);
  const [loadingChat, setLoadingChat] = useState(false);
  const [error, setError] = useState('');
  const [grill, setGrill] = useState<GrillState | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const streamingRef = useRef('');
  const finishedRef = useRef(false);
  const startedRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const currentTitle = history.data?.find((item) => item.id === currentId)?.title || (currentId ? '当前对话' : '新对话');

  const loadConversation = useCallback(async (id: string) => {
    setLoadingChat(true); setError(''); setGrill(null);
    try { const conversation = await api.conversation(id); setMessages(conversation.messages || []); setCurrentId(id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '对话加载失败'); }
    finally { setLoadingChat(false); }
  }, []);
  useEffect(() => { if (routeId) void loadConversation(routeId); else { setCurrentId(null); setMessages([]); setGrill(null); } }, [routeId, loadConversation]);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: generating ? 'auto' : 'smooth' }); }, [messages, streaming, grill, generating]);

  const startAsk = useCallback(async (question: string, appendUser = true) => {
    const text = question.trim();
    if (!text || generating) return;
    setInput(''); setError(''); setGrill(null); setGenerating(true); setStreaming(''); streamingRef.current = ''; finishedRef.current = false;
    if (appendUser) setMessages((items) => [...items, { id: crypto.randomUUID(), role: 'user', content: text }]);
    const controller = new AbortController(); abortRef.current = controller;
    try {
      let id = currentId;
      if (!id) {
        const conversation = await api.createConversation(text.slice(0, 24)); id = conversation.id; setCurrentId(id);
        history.setData((history.data || []).some((item) => item.id === id) ? history.data : [conversation, ...(history.data || [])]);
      }
      await api.askStream(text, id, controller.signal, {
        onToken: (token) => { streamingRef.current += token; setStreaming(streamingRef.current); },
        onGrill: (state) => setGrill(state),
        onDone: (message) => {
          if (finishedRef.current) return; finishedRef.current = true;
          const content = message?.content || streamingRef.current;
          if (content) setMessages((items) => [...items, { id: message?.id || crypto.randomUUID(), role: 'assistant', content, kind: message?.kind || inferKind(text, content) }]);
          setStreaming(''); setGenerating(false);
        },
      });
    } catch (reason) {
      if (controller.signal.aborted) {
        if (streamingRef.current) setMessages((items) => [...items, { id: crypto.randomUUID(), role: 'assistant', content: streamingRef.current, kind: 'advice' }]);
        setStreaming(''); toast('已停止生成');
      } else setError(reason instanceof Error ? reason.message : '生成失败，请重试');
      setGenerating(false);
    } finally { abortRef.current = null; }
  }, [currentId, generating, history, toast]);
  useEffect(() => {
    if (initialPrompt && !startedRef.current) { startedRef.current = true; void startAsk(initialPrompt); }
  }, [initialPrompt, startAsk]);

  const newChat = () => { abortRef.current?.abort(); setHistoryOpen(false); navigate('/chat'); setMessages([]); setInput(''); setError(''); };
  const selectChat = (id: string) => { setHistoryOpen(false); navigate(`/chat/${id}`); };
  const archive = async (id: string) => {
    try { await api.archiveConversation(id); history.setData((history.data || []).filter((item) => item.id !== id)); if (id === currentId) newChat(); toast('对话已归档'); }
    catch (reason) { toast(reason instanceof Error ? reason.message : '归档失败', 'error'); }
  };
  const remove = async () => {
    if (!deleteId) return;
    try { await api.deleteConversation(deleteId); history.setData((history.data || []).filter((item) => item.id !== deleteId)); if (deleteId === currentId) newChat(); setDeleteId(null); toast('对话已删除'); }
    catch (reason) { toast(reason instanceof Error ? reason.message : '删除失败', 'error'); }
  };
  const answerGrill = async (value: string) => {
    if (!currentId || !grill?.question) return;
    await startAsk(value);
  };
  const regenerate = async () => {
    if (!currentId || generating) return; setGenerating(true); setError('');
    try { const message = await api.regenerate(currentId); setMessages((items) => [...items, message]); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '重新生成失败'); }
    finally { setGenerating(false); }
  };
  const feedback = async (message: Message, value: 'up' | 'down') => {
    try { await api.feedback(message.id, value); setMessages((items) => items.map((item) => item.id === message.id ? { ...item, feedback: value } : item)); toast('感谢你的反馈'); }
    catch (reason) { toast(reason instanceof Error ? reason.message : '反馈未保存', 'error'); }
  };
  const saveRecord = async (message: Message) => {
    const firstLine = message.content.split('\n').find(Boolean) || 'AI 对话中的饮食';
    await mealRecordService.create({ date: toDateKey(), meal_type: /早餐/.test(message.content) ? 'breakfast' : /午餐/.test(message.content) ? 'lunch' : 'dinner', food_name: firstLine.slice(0, 36), note: message.content, source: 'chat' });
    toast('已保存到本机饮食记录');
  };
  const savePlan = async (message: Message) => { await mealPlanService.saveFromMessage(message.content); toast('已保存到餐食推荐'); };
  const lastQuestion = [...messages].reverse().find((item) => item.role === 'user')?.content;
  const listProps = { conversations: history.data || [], activeId: currentId || undefined, loading: history.loading, error: history.error, onRetry: () => void history.retry(), onSelect: selectChat, onNew: newChat, onArchive: (id: string) => void archive(id), onDelete: setDeleteId };

  return <div className="flex h-[calc(100dvh-153px)] min-h-[480px] lg:h-screen lg:min-h-[560px]"><ConversationList {...listProps} />{historyOpen && <><button className="fixed inset-0 z-40 bg-stone-900/30 lg:hidden" aria-label="关闭历史" onClick={() => setHistoryOpen(false)} /><ConversationList {...listProps} mobile onClose={() => setHistoryOpen(false)} /></>}<main className="flex min-w-0 flex-1 flex-col"><header className="flex min-h-16 items-center gap-2 border-b bg-paper px-3 sm:px-6" style={{ borderColor: 'var(--border-subtle)' }}><button className="icon-btn lg:hidden" aria-label="打开对话历史" onClick={() => setHistoryOpen(true)}><ClockCounterClockwise size={22} /></button><div className="min-w-0 flex-1"><h1 className="truncate font-sans text-base font-semibold">{currentTitle}</h1><p className="flex items-center gap-1 text-xs leading-5 subtle"><span className={`size-1.5 rounded-full ${grill?.status === 'waiting' ? 'bg-apricot' : 'bg-sage'}`} />{grill?.status === 'waiting' ? '等待你补充一项信息' : grill?.status === 'ready' ? '信息已足够' : 'AI 会根据现有信息回答'}</p></div><button className="icon-btn" aria-label="新建对话" onClick={newChat}><Plus size={22} /></button></header><div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto"><div className="mx-auto flex min-h-full w-full max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">{loadingChat ? <LoadingState label="正在读取对话" /> : messages.length === 0 && !generating ? <EmptyState icon={<Leaf size={27} weight="light" />} title="今天想了解什么？" description="可以问食物热量、一餐搭配或饮食习惯。只有当你明确要求制定餐食时，才会进入规划流程。" action={<div className="flex flex-wrap justify-center gap-2">{['鸡胸肉的热量', '我想减脂', '帮我安排晚餐'].map((item) => <button key={item} className="btn btn-secondary" onClick={() => void startAsk(item)}>{item}</button>)}</div>} /> : messages.map((message, index) => <ChatMessage key={message.id} message={message} isLatest={index === messages.length - 1 && message.role === 'assistant'} onRegenerate={() => void regenerate()} onFeedback={(value) => void feedback(message, value)} onSaveRecord={() => void saveRecord(message)} onSavePlan={() => void savePlan(message)} />)}{generating && streaming && <StreamingMessage content={streaming} />}{generating && !streaming && !grill && <StreamingMessage content="" />}{grill && <GrillQuestionCard state={grill} busy={generating} onAnswer={(value) => void answerGrill(value)} onExecute={() => void startAsk('以上信息已确认，请继续生成餐食计划')} />}{error && <div className="rounded-card bg-red-50 p-4 text-red-900" role="alert"><div className="flex items-start gap-2"><WarningCircle size={21} className="mt-0.5 shrink-0" /><div><p className="text-sm font-semibold">这次没有完成</p><p className="mt-1 text-sm">{error}</p></div></div>{lastQuestion && <button className="btn mt-3 bg-white text-red-900" onClick={() => void startAsk(lastQuestion, false)}>重试上一问题</button>}</div>}</div></div><footer className="border-t bg-paper px-3 pb-[max(12px,env(safe-area-inset-bottom))] pt-3 sm:px-6" style={{ borderColor: 'var(--border-subtle)' }}><div className="mx-auto max-w-3xl">{generating && <div className="mb-2 flex justify-center"><button className="btn btn-ghost min-h-8 text-xs" onClick={() => abortRef.current?.abort()}><Stop size={15} />停止生成</button></div>}<form className="flex items-end gap-2" onSubmit={(event) => { event.preventDefault(); void startAsk(input); }}><label htmlFor="chat-input" className="sr-only">向营养助手提问</label><textarea id="chat-input" className="input max-h-32 !min-h-12 flex-1 resize-none py-3" rows={1} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void startAsk(input); } }} placeholder="说说你的问题或今天吃了什么…" disabled={generating} /><button className="btn btn-primary size-12 shrink-0 px-0" aria-label="发送问题" disabled={!input.trim() || generating}><ArrowUp size={21} /></button></form><p className="mt-2 text-center text-xs leading-5 subtle">营养信息为估算与生活方式建议，不替代专业医疗诊断。</p></div></footer></main><ConfirmDialog open={Boolean(deleteId)} title="删除这段对话？" description="删除后将无法在对话历史中找回。你的个人档案和知识库不会受影响。" onCancel={() => setDeleteId(null)} onConfirm={() => void remove()} /></div>;
}
