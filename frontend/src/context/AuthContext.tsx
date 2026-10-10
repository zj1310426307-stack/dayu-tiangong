import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError, getCurrentPrincipal, setAuthAccessToken, type CurrentPrincipalRecord } from '../api/generated/client';

interface AuthContextValue {
  principal: CurrentPrincipalRecord | null;
  loading: boolean;
  error: string | null;
  can: (permission: string) => boolean;
  refresh: () => Promise<void>;
  setAccessToken: (token: string | null) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** Resolve the current user from the backend; the external OIDC host owns token acquisition. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [principal, setPrincipal] = useState<CurrentPrincipalRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setPrincipal(await getCurrentPrincipal());
      setError(null);
    } catch (reason) {
      setPrincipal(null);
      setError(
        reason instanceof ApiError && reason.status === 401
          ? '未登录或身份提供方尚未配置'
          : reason instanceof Error ? reason.message : '身份校验失败',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const setAccessToken = useCallback(async (token: string | null) => {
    setAuthAccessToken(token);
    await refresh();
  }, [refresh]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<AuthContextValue>(() => ({
    principal,
    loading,
    error,
    can: (permission) => principal?.permissions.includes(permission) ?? false,
    refresh,
    setAccessToken,
  }), [error, loading, principal, refresh, setAccessToken]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Return trusted identity state; mutation controls must still rely on backend enforcement. */
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}
