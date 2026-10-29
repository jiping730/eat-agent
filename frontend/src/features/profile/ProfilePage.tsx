import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, BookOpenText, Check, Info, LockKey, SignOut, X } from '@phosphor-icons/react';
import { api } from '../../services/api';
import { useAsync } from '../../hooks/useAsync';
import { useApp } from '../../app/AppContext';
import type { Profile, ProfileSuggestion } from '../../types';
import { PageHeader } from '../../components/PageHeader';
import { LoadingState, ErrorState, InlineNotice, Badge } from '../../components/State';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { ProfileForm } from './ProfileForm';

const blankProfile: Profile = { nickname: '', dietary_preferences: [], restrictions: [], allergies: [], memory_enabled: false, personalization_enabled: false };
export function ProfilePage() {
  const { user, logout, toast } = useApp();
  const navigate = useNavigate();
  const { data, loading, error, retry } = useAsync(async () => {
    const [profile, settings, suggestions] = await Promise.all([api.profile(), api.experienceSettings(), api.profileSuggestions().catch(() => [] as ProfileSuggestion[])]);
    return { profile: { ...blankProfile, ...profile, dietary_preferences: profile.dietary_preferences || [], restrictions: profile.restrictions || [], allergies: profile.allergies || [] }, settings, suggestions };
  }, []);
  const [busy, setBusy] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [ignored, setIgnored] = useState<string[]>([]);
  const save = async (profile: Profile) => {
    setBusy(true);
    try { await api.updateProfile(profile); toast('健康档案已保存'); await retry(); }
    catch (reason) { toast(reason instanceof Error ? reason.message : '档案保存失败', 'error'); }
    finally { setBusy(false); }
  };
  const updateSettings = async (memory: boolean, personalization: boolean) => {
    if (!data) return; setBusy(true);
    try { await api.updateExperienceSettings({ memory_enabled: memory, personalization_enabled: personalization }); toast('个性化设置已更新'); setMemoryOpen(false); await retry(); }
    catch (reason) { toast(reason instanceof Error ? reason.message : '设置保存失败', 'error'); }
    finally { setBusy(false); }
  };
  const acceptSuggestion = async (suggestion: ProfileSuggestion) => {
    if (!data) return;
    const current = data.profile[suggestion.field];
    const value = Array.isArray(current) ? [...current, suggestion.value] : suggestion.value;
    await save({ ...data.profile, [suggestion.field]: value });
  };
  if (loading) return <div className="page"><LoadingState /></div>;
  if (error || !data) return <div className="page"><ErrorState message={error || '档案加载失败'} onRetry={() => void retry()} /></div>;
  const clearProfile = async () => {
    setBusy(true);
    try { await api.deleteProfile(); toast('个人资料已清除'); setClearOpen(false); await retry(); }
    catch (reason) { toast(reason instanceof Error ? reason.message : '资料清除失败', 'error'); }
    finally { setBusy(false); }
  };
  return <div className="page page-narrow"><PageHeader eyebrow="由你掌握的信息" title="我的健康档案" description="这些信息会影响 AI 的建议。所有项目都可以留空，也可以随时修改或清除。" /><div className="mb-6"><InlineNotice>年龄、身高、体重、目标、活动水平、偏好、忌口与过敏信息会参与个性化建议。请不要填写与饮食无关的敏感信息。</InlineNotice></div>{data.suggestions.filter((item) => !ignored.includes(item.id)).length > 0 && <section className="card card-pad mb-6"><h2 className="font-sans text-lg font-semibold">来自对话的资料建议</h2><p className="mt-1 text-sm muted">只有你接受后，才会写入健康档案。</p><div className="mt-4 space-y-3">{data.suggestions.filter((item) => !ignored.includes(item.id)).map((suggestion) => <div key={suggestion.id} className="rounded-control bg-mint p-4"><p className="text-sm font-semibold">{suggestion.label}：{suggestion.value}</p><p className="mt-1 text-xs leading-5 muted">{suggestion.reason}</p><div className="mt-3 flex gap-2"><button className="btn btn-primary min-h-9 text-xs" onClick={() => void acceptSuggestion(suggestion)}><Check size={16} />接受</button><button className="btn btn-ghost min-h-9 text-xs" onClick={() => navigate(`/chat?prompt=${encodeURIComponent(`我想修改资料建议：${suggestion.label} ${suggestion.value}`)}`)}>修改</button><button className="icon-btn size-9" aria-label="忽略建议" onClick={() => setIgnored([...ignored, suggestion.id])}><X size={16} /></button></div></div>)}</div></section>}<ProfileForm key={JSON.stringify(data.profile)} initial={data.profile} busy={busy} onSubmit={(value) => void save(value)} /><section className="card card-pad mt-8"><div className="flex items-start gap-3"><LockKey size={23} className="mt-1 shrink-0 text-sage" weight="light" /><div><h2 className="font-sans text-lg font-semibold">记忆与个性化</h2><p className="mt-1 text-sm leading-6 muted">关闭后，轻松食将不再使用对应信息提供个性化建议。具体记忆清除范围以后端返回为准。</p></div></div><div className="mt-5 space-y-4"><label className="flex min-h-11 cursor-pointer items-center justify-between gap-4"><span><span className="block text-sm font-semibold">对话记忆</span><span className="text-xs muted">保留用于连续交流的偏好</span></span><input type="checkbox" className="size-5 accent-[#285a4a]" checked={data.settings.memory_enabled} onChange={(e) => e.target.checked ? void updateSettings(true, data.settings.personalization_enabled) : setMemoryOpen(true)} /></label><label className="flex min-h-11 cursor-pointer items-center justify-between gap-4"><span><span className="block text-sm font-semibold">个性化建议</span><span className="text-xs muted">允许使用已填写的健康档案</span></span><input type="checkbox" className="size-5 accent-[#285a4a]" checked={data.settings.personalization_enabled} onChange={(e) => void updateSettings(data.settings.memory_enabled, e.target.checked)} /></label></div></section><section className="card card-pad mt-6"><div className="flex items-center gap-3"><BookOpenText size={23} className="text-sage" weight="light" /><div className="flex-1"><h2 className="font-sans text-lg font-semibold">个人知识库</h2><p className="text-sm muted">管理仅你可见的文档与检索状态</p></div><button className="icon-btn" aria-label="打开个人知识库" onClick={() => navigate('/knowledge')}><ArrowRight size={21} /></button></div></section><div className="mt-8 flex flex-col gap-2 border-t pt-6 sm:flex-row sm:justify-between" style={{ borderColor: 'var(--border-subtle)' }}><button className="btn btn-ghost justify-start text-red-800" onClick={() => setClearOpen(true)}>清除个人资料</button><button className="btn btn-ghost justify-start" onClick={() => void logout().then(() => navigate('/login')).catch((reason) => toast(reason.message, 'error'))}><SignOut size={18} />退出登录</button></div><ConfirmDialog open={clearOpen} title="清除全部个人资料？" description="将清空健康档案中的基础资料、目标、偏好、忌口和过敏信息，并关闭个性化设置。对话与个人文档不会因此删除。" confirmLabel="清除个人资料" busy={busy} onCancel={() => setClearOpen(false)} onConfirm={() => void clearProfile()} /><ConfirmDialog open={memoryOpen} title="关闭对话记忆？" description="关闭后，后续建议将不再使用对话记忆。历史对话本身不会自动删除。" confirmLabel="关闭记忆" busy={busy} onCancel={() => setMemoryOpen(false)} onConfirm={() => void updateSettings(false, data.settings.personalization_enabled)} /></div>;
}
