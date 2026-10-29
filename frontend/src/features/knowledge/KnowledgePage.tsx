import { useRef, useState, type FormEvent } from 'react';
import { BookOpenText, FilePlus, MagnifyingGlass, Plus, UploadSimple, X } from '@phosphor-icons/react';
import { api } from '../../services/api';
import { useAsync } from '../../hooks/useAsync';
import { useApp } from '../../app/AppContext';
import type { KnowledgeDocument } from '../../types';
import { PageHeader } from '../../components/PageHeader';
import { LoadingState, ErrorState, EmptyState, InlineNotice } from '../../components/State';
import { KnowledgeDocumentList } from './KnowledgeDocumentList';
import { ConfirmDialog } from '../../components/ConfirmDialog';

export function KnowledgePage() {
  const { toast } = useApp();
  const { data: documents, loading, error, retry } = useAsync(() => api.documents(), []);
  const [formOpen, setFormOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [busy, setBusy] = useState(false);
  const [deleteDoc, setDeleteDoc] = useState<KnowledgeDocument | null>(null);
  const [query, setQuery] = useState('');
  const [searched, setSearched] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true);
    try { await api.addDocument(title.trim(), content.trim()); setTitle(''); setContent(''); setFormOpen(false); await retry(); toast('文档已添加，正在建立索引'); setTimeout(() => void retry(), 1500); }
    catch (reason) { toast(reason instanceof Error ? reason.message : '文档添加失败', 'error'); }
    finally { setBusy(false); }
  };
  const importFile = async (file?: File) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { toast('开发导入限制为 2MB，请选择较小文档', 'error'); return; }
    if (!/\.(txt|md)$/i.test(file.name)) { toast('当前支持 TXT 和 Markdown 文档', 'error'); return; }
    setTitle(file.name.replace(/\.(txt|md)$/i, '')); setContent(await file.text()); setFormOpen(true);
    if (fileRef.current) fileRef.current.value = '';
  };
  const remove = async () => {
    if (!deleteDoc) return;
    try { await api.deleteDocument(deleteDoc.id); setDeleteDoc(null); await retry(); toast('文档已删除'); }
    catch (reason) { toast(reason instanceof Error ? reason.message : '删除失败', 'error'); }
  };
  const results = query.trim() && documents ? documents.filter((doc) => `${doc.title}\n${doc.content || ''}`.toLowerCase().includes(query.trim().toLowerCase())) : [];
  return <div className="page page-narrow"><PageHeader eyebrow="只属于你" title="个人知识库" description="保存自己的饮食笔记和参考资料。这里不会展示管理端知识库内容。" action={<button className="btn btn-primary" onClick={() => setFormOpen(true)}><Plus size={18} />添加文档</button>} /><div className="mb-6 flex items-center gap-3"><input ref={fileRef} type="file" accept=".txt,.md,text/plain,text/markdown" className="hidden" onChange={(e) => void importFile(e.target.files?.[0])} /><button className="btn btn-outline" onClick={() => fileRef.current?.click()}><UploadSimple size={18} />导入 TXT / MD</button><p className="text-xs subtle">单个文件不超过 2MB</p></div>{loading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={() => void retry()} /> : documents?.length ? <KnowledgeDocumentList documents={documents} onDelete={setDeleteDoc} /> : <div className="card"><EmptyState icon={<BookOpenText size={27} weight="light" />} title="还没有个人文档" description="可以从一段饮食心得或一份常用食材清单开始。" action={<button className="btn btn-secondary" onClick={() => setFormOpen(true)}><FilePlus size={18} />写下第一份文档</button>} /></div>}{documents && documents.length > 0 && <section className="card card-pad mt-8"><h2 className="flex items-center gap-2 font-sans text-lg font-semibold"><MagnifyingGlass size={21} />测试检索</h2><p className="mt-1 text-sm muted">在已加载的个人文档标题与内容中测试关键词；不代表服务端向量检索结果。</p><form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); setSearched(true); }}><label className="sr-only" htmlFor="knowledge-query">检索关键词</label><input id="knowledge-query" className="input" value={query} onChange={(e) => { setQuery(e.target.value); setSearched(false); }} placeholder="例如：早餐、蛋白质" /><button className="btn btn-secondary shrink-0" disabled={!query.trim()}>查找</button></form>{searched && <div className="mt-4 rounded-control bg-stone-50 p-4 text-sm" aria-live="polite">{results.length ? <><p className="font-semibold">找到 {results.length} 份相关文档</p><ul className="mt-2 list-disc pl-5 muted">{results.map((doc) => <li key={doc.id}>{doc.title} · {doc.status === 'ready' ? '可检索' : '索引构建中'}</li>)}</ul></> : <p className="muted">没有匹配内容，试试更短的关键词。</p>}</div>}</section>}<div className="mt-6"><InlineNotice>文档只用于你的个人知识检索。索引构建完成后才能参与 AI 回答；失败时可在后端日志中排查原因。</InlineNotice></div>{formOpen && <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/35 sm:items-center sm:p-4"><form className="max-h-[94dvh] w-full max-w-xl overflow-y-auto rounded-t-card bg-paper p-6 shadow-lift sm:rounded-card" onSubmit={submit}><div className="mb-6 flex items-center justify-between"><h2 className="text-2xl">添加个人文档</h2><button type="button" className="icon-btn" aria-label="关闭" onClick={() => setFormOpen(false)}><X size={22} /></button></div><div className="space-y-5"><label className="field">标题<input className="input" required maxLength={100} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：我的工作日早餐笔记" /></label><label className="field">内容<textarea className="input min-h-64" required value={content} onChange={(e) => setContent(e.target.value)} placeholder="粘贴或写下需要保留的内容…" /></label></div><button className="btn btn-primary mt-6 w-full" disabled={busy || !title.trim() || !content.trim()}>{busy ? '正在添加…' : '添加并开始构建索引'}</button></form></div>}<ConfirmDialog open={Boolean(deleteDoc)} title="删除这份文档？" description={`“${deleteDoc?.title || ''}”及其个人索引将被删除，无法撤销。`} onCancel={() => setDeleteDoc(null)} onConfirm={() => void remove()} /></div>;
}
