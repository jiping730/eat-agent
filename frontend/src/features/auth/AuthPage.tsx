import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { ArrowRight, Leaf, ShieldCheck } from '@phosphor-icons/react';
import { api } from '../../services/api';
import { useApp } from '../../app/AppContext';
import { InlineNotice } from '../../components/State';

export function AuthPage() {
  const { user, setUser } = useApp();
  const navigate = useNavigate();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [nickname, setNickname] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [registered, setRegistered] = useState(false);
  if (user) return <Navigate to="/" replace />;
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError('');
    if (username.trim().length < 3) { setError('用户名至少需要 3 个字符'); return; }
    if (password.length < 8) { setError('密码至少需要 8 个字符'); return; }
    setBusy(true);
    try {
      if (mode === 'register') {
        const result = await api.register(username.trim(), password, nickname.trim());
        if (!('access_token' in result)) await api.login(username.trim(), password);
        setRegistered(true);
      } else await api.login(username.trim(), password);
      setUser(await api.me());
      navigate('/', { replace: true });
    } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败，请稍后重试'); }
    finally { setBusy(false); }
  };
  return <main className="min-h-screen bg-cream px-5 py-8 sm:flex sm:items-center sm:justify-center"><div className="mx-auto w-full max-w-[440px]"><div className="mb-10 flex items-center gap-3"><span className="flex size-11 items-center justify-center rounded-full bg-sage text-paper"><Leaf size={25} weight="light" /></span><div><p className="font-display text-2xl font-bold">轻松食</p><p className="text-xs subtle">你的个人营养助手</p></div></div><section className="card p-6 sm:p-8"><p className="mb-3 text-xs font-semibold tracking-[.14em] text-sage">好好吃饭，慢慢了解自己</p><h1 className="text-3xl">{mode === 'login' ? '欢迎回来' : '从这里开始'}</h1><p className="mt-3 text-sm leading-6 muted">{mode === 'login' ? '继续你的饮食记录与营养对话。' : '只需要一个账号，健康信息之后由你决定是否补充。'}</p>{registered && <div className="mt-5"><InlineNotice tone="success">注册成功。接下来可以先完善健康档案，也可以直接开始对话。</InlineNotice></div>}<form className="mt-8 space-y-5" onSubmit={submit} noValidate>{mode === 'register' && <label className="field">怎么称呼你<input className="input" value={nickname} onChange={(e) => setNickname(e.target.value)} autoComplete="nickname" maxLength={30} placeholder="昵称（可选）" /></label>}<label className="field">用户名<input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required minLength={3} maxLength={128} placeholder="至少 3 个字符" /></label><label className="field">密码<input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required minLength={8} placeholder="至少 8 个字符" /></label>{error && <p className="rounded-control bg-red-50 p-3 text-sm leading-6 text-red-800" role="alert">{error}</p>}<button className="btn btn-primary w-full" disabled={busy}>{busy ? '正在处理…' : mode === 'login' ? '登录并继续' : '创建我的账号'}<ArrowRight size={18} /></button></form><div className="mt-6 text-center text-sm muted">{mode === 'login' ? '还没有账号？' : '已经有账号？'}<button className="ml-1 min-h-11 font-semibold text-sage underline decoration-sage/30 underline-offset-4" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); setRegistered(false); }}>{mode === 'login' ? '注册' : '返回登录'}</button></div></section><p className="mx-auto mt-6 flex max-w-sm items-start justify-center gap-2 text-center text-xs leading-5 subtle"><ShieldCheck size={17} className="mt-0.5 shrink-0" />健康信息仅用于个性化建议，你可以随时查看、修改或清除。</p></div></main>;
}
