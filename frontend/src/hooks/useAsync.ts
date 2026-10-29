import { useCallback, useEffect, useState } from 'react';

export function useAsync<T>(loader: () => Promise<T>, deps: React.DependencyList = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const execute = useCallback(async () => {
    setLoading(true); setError('');
    try { setData(await loader()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '加载失败，请重试'); }
    finally { setLoading(false); }
  }, deps);
  useEffect(() => { void execute(); }, [execute]);
  return { data, setData, loading, error, retry: execute };
}
