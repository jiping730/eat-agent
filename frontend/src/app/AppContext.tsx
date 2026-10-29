import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, isMockMode, tokenStore } from '../services/api';
import type { User } from '../types';

type Toast = { id: string; message: string; tone: 'success' | 'error' };
type AppContextValue = {
  user: User | null;
  authLoading: boolean;
  authError: string;
  setUser: (user: User | null) => void;
  refreshUser: () => Promise<void>;
  logout: () => Promise<void>;
  toast: (message: string, tone?: Toast['tone']) => void;
  toasts: Toast[];
};
const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState('');
  const [toasts, setToasts] = useState<Toast[]>([]);
  const refreshUser = useCallback(async () => {
    setAuthLoading(true); setAuthError('');
    if (!tokenStore.access && !isMockMode) { setUser(null); setAuthLoading(false); return; }
    try { setUser(await api.me()); }
    catch (error) {
      setUser(null);
      if (!(error instanceof Error && 'status' in error && error.status === 401)) setAuthError(error instanceof Error ? error.message : '身份校验失败');
    } finally { setAuthLoading(false); }
  }, []);
  useEffect(() => { void refreshUser(); }, [refreshUser]);
  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener('eat:unauthorized', onUnauthorized);
    return () => window.removeEventListener('eat:unauthorized', onUnauthorized);
  }, []);
  const toast = useCallback((message: string, tone: Toast['tone'] = 'success') => {
    const id = crypto.randomUUID(); setToasts((items) => [...items, { id, message, tone }]);
    window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 3200);
  }, []);
  const logout = useCallback(async () => { await api.logout(); setUser(null); }, []);
  const value = useMemo(() => ({ user, authLoading, authError, setUser, refreshUser, logout, toast, toasts }), [user, authLoading, authError, refreshUser, logout, toast, toasts]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
export function useApp() {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used inside AppProvider');
  return context;
}
