import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  getDatasetVersions,
  type DatasetVersionRecord,
} from '../api/generated/client';

interface DatasetVersionContextValue {
  versions: DatasetVersionRecord[];
  datasetVersionId?: number;
  currentVersion?: DatasetVersionRecord;
  isMutable: boolean;
  loading: boolean;
  error: string;
  setDatasetVersionId: (value: number) => void;
  refreshVersions: (preferredId?: number) => Promise<void>;
}

const DatasetVersionContext = createContext<DatasetVersionContextValue | null>(null);
const STORAGE_KEY = 'dayu.datasetVersionId';

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿可编辑',
  review: '审核中',
  approved: '已批准',
  published: '已发布只读',
  retired: '已退役只读',
  rejected: '已驳回',
};

/** 把后端生命周期状态转换为全站一致的中文标签。 */
export function datasetVersionStatusLabel(status?: string): string {
  return status ? STATUS_LABELS[status] ?? status : '状态未知';
}

/** 阅读模式默认选择最新发布版本，避免回退到最旧的历史版本。 */
function defaultVersionId(items: DatasetVersionRecord[]): number | undefined {
  const published = items.filter((item) => item.status === 'published');
  const candidates = published.length ? published : items;
  return candidates.reduce<number | undefined>(
    (latest, item) => latest === undefined || item.id > latest ? item.id : latest,
    undefined,
  );
}

/** 维护全局数据版本身份，并在切换版本时清理不可跨版本复用的页面状态。 */
export function DatasetVersionProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [versions, setVersions] = useState<DatasetVersionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const queryValue = Number(new URLSearchParams(location.search).get('datasetVersionId'));
  const storedValue = Number(window.localStorage.getItem(STORAGE_KEY));
  const [datasetVersionId, setValue] = useState<number | undefined>(
    queryValue > 0 ? queryValue : storedValue > 0 ? storedValue : undefined,
  );

  useEffect(() => {
    void getDatasetVersions()
      .then((items) => {
        setVersions(items);
        setError('');
        setValue((current) => {
          const next = current && items.some((item) => item.id === current)
            ? current
            : defaultVersionId(items);
          if (next) window.localStorage.setItem(STORAGE_KEY, String(next));
          return next;
        });
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : '数据版本加载失败');
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (queryValue > 0 && versions.some((item) => item.id === queryValue)) {
      setValue(queryValue);
      window.localStorage.setItem(STORAGE_KEY, String(queryValue));
    }
  }, [queryValue, versions]);

  const setDatasetVersionId = useCallback((value: number) => {
    setValue(value);
    window.localStorage.setItem(STORAGE_KEY, String(value));
    const params = new URLSearchParams(location.search);
    // Task, dispatch, selected feature and time identities cannot cross dataset versions.
    params.delete('taskId');
    params.delete('dispatchRunId');
    params.delete('selectedAsset');
    params.set('time', '0');
    params.set('datasetVersionId', String(value));
    navigate(`${location.pathname}?${params.toString()}`, { replace: true });
  }, [location.pathname, location.search, navigate]);

  const refreshVersions = useCallback(async (preferredId?: number) => {
    setLoading(true);
    try {
      const items = await getDatasetVersions();
      setVersions(items);
      setError('');
      if (preferredId && items.some((item) => item.id === preferredId)) {
        setDatasetVersionId(preferredId);
        return;
      }
      setValue((current) => {
        const next = current && items.some((item) => item.id === current)
          ? current
          : defaultVersionId(items);
        if (next) window.localStorage.setItem(STORAGE_KEY, String(next));
        return next;
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '数据版本加载失败');
      throw reason;
    } finally {
      setLoading(false);
    }
  }, [setDatasetVersionId]);

  const currentVersion = useMemo(
    () => versions.find((item) => item.id === datasetVersionId),
    [datasetVersionId, versions],
  );
  const isMutable = currentVersion?.status === 'draft';
  const contextValue = useMemo(
    () => ({
      versions,
      datasetVersionId,
      currentVersion,
      isMutable,
      loading,
      error,
      setDatasetVersionId,
      refreshVersions,
    }),
    [versions, datasetVersionId, currentVersion, isMutable, loading, error, setDatasetVersionId, refreshVersions],
  );
  return (
    <DatasetVersionContext.Provider value={contextValue}>
      {children}
    </DatasetVersionContext.Provider>
  );
}

/** 返回当前数据版本状态；只能在 DatasetVersionProvider 内调用。 */
export function useDatasetVersion(): DatasetVersionContextValue {
  const value = useContext(DatasetVersionContext);
  if (!value) throw new Error('useDatasetVersion must be used inside DatasetVersionProvider');
  return value;
}
