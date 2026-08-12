import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  getDatasetVersions,
  type DatasetVersionRecord,
} from '../api/generated/client';

interface DatasetVersionContextValue {
  versions: DatasetVersionRecord[];
  datasetVersionId?: number;
  loading: boolean;
  setDatasetVersionId: (value: number) => void;
}

const DatasetVersionContext = createContext<DatasetVersionContextValue | null>(null);
const STORAGE_KEY = 'dayu.datasetVersionId';

export function DatasetVersionProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [versions, setVersions] = useState<DatasetVersionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const queryValue = Number(new URLSearchParams(location.search).get('datasetVersionId'));
  const storedValue = Number(window.localStorage.getItem(STORAGE_KEY));
  const [datasetVersionId, setValue] = useState<number | undefined>(
    queryValue > 0 ? queryValue : storedValue > 0 ? storedValue : undefined,
  );

  useEffect(() => {
    void getDatasetVersions()
      .then((items) => {
        setVersions(items);
        setValue((current) => {
          if (current && items.some((item) => item.id === current)) return current;
          return items[0]?.id;
        });
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (queryValue > 0 && versions.some((item) => item.id === queryValue)) {
      setValue(queryValue);
    }
  }, [queryValue, versions]);

  const setDatasetVersionId = (value: number) => {
    setValue(value);
    window.localStorage.setItem(STORAGE_KEY, String(value));
    const params = new URLSearchParams(location.search);
    params.set('datasetVersionId', String(value));
    navigate(`${location.pathname}?${params.toString()}`, { replace: true });
  };

  const contextValue = useMemo(
    () => ({ versions, datasetVersionId, loading, setDatasetVersionId }),
    [versions, datasetVersionId, loading],
  );
  return (
    <DatasetVersionContext.Provider value={contextValue}>
      {children}
    </DatasetVersionContext.Provider>
  );
}

export function useDatasetVersion(): DatasetVersionContextValue {
  const value = useContext(DatasetVersionContext);
  if (!value) throw new Error('useDatasetVersion must be used inside DatasetVersionProvider');
  return value;
}
