import { FileText, Trash } from '@phosphor-icons/react';
import type { KnowledgeDocument } from '../../types';
import { Badge } from '../../components/State';

const status = { indexing: ['构建中', 'orange'], ready: ['可检索', 'green'], failed: ['索引失败', 'red'] } as const;
export function KnowledgeDocumentList({ documents, onDelete }: { documents: KnowledgeDocument[]; onDelete: (document: KnowledgeDocument) => void }) {
  return <div className="card divide-y" style={{ borderColor: 'var(--border-subtle)' }}>{documents.map((document) => <article key={document.id} className="flex items-start gap-3 p-4"><span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-mint text-sage"><FileText size={21} weight="light" /></span><div className="min-w-0 flex-1"><h3 className="truncate font-semibold">{document.title}</h3><div className="mt-2 flex flex-wrap items-center gap-2"><Badge tone={status[document.status][1]}>{status[document.status][0]}</Badge>{document.created_at && <span className="text-xs subtle">{new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' }).format(new Date(document.created_at))}</span>}</div></div><button className="icon-btn" aria-label={`删除${document.title}`} onClick={() => onDelete(document)}><Trash size={18} /></button></article>)}</div>;
}
