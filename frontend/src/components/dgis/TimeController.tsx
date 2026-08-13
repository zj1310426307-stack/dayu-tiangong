import { Button, Card, DatePicker, Space, Tag, message } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useState } from 'react';

import { replayDGISFeatureStates, type FeatureStateCollection } from '../../api/generated/client';


interface TimeControllerProps {
  datasetVersionId: number;
  onReplay: (value: FeatureStateCollection | null) => void;
}


/** Restore the latest gate, pump, monitoring, and risk state at an absolute instant. */
export function TimeController({ datasetVersionId, onReplay }: TimeControllerProps) {
  const [at, setAt] = useState<Dayjs>(dayjs('2026-08-13T09:00:00+08:00'));
  const [loading, setLoading] = useState(false);
  const [count, setCount] = useState(0);
  const replay = async () => {
    setLoading(true);
    try {
      const result = await replayDGISFeatureStates({ dataset_version_id: datasetVersionId, at: at.toISOString() });
      onReplay(result);
      setCount(result.total);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '时空回放失败');
    } finally {
      setLoading(false);
    }
  };
  return (
    <Card size="small" title="TimeController · 绝对时间回放">
      <Space wrap>
        <DatePicker showTime value={at} onChange={(value) => value && setAt(value)} />
        <Button type="primary" loading={loading} onClick={() => void replay()}>恢复状态</Button>
        <Tag color="cyan">{count} 个对象</Tag>
      </Space>
    </Card>
  );
}
