import { FilePdfOutlined } from '@ant-design/icons';
import { Button, message } from 'antd';
import { useState } from 'react';
import { downloadGISThematicMap } from '../../api/generated/client';

interface MapExportProps {
  datasetVersionId: number;
  timeSeconds: number;
  taskId?: number;
}

/** Download the authoritative backend-rendered map while keeping cartography off the UI layer. */
export function MapExport({ datasetVersionId, timeSeconds, taskId }: MapExportProps) {
  const [loading, setLoading] = useState(false);

  async function exportPdf() {
    setLoading(true);
    try {
      const blob = await downloadGISThematicMap({
        dataset_version_id: datasetVersionId, time_seconds: timeSeconds, task_id: taskId,
        title: '大禹·天工 Phase 1D 水动力专题图', author: 'Dayu Tiangong',
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `dayu-phase1d-version-${datasetVersionId}.pdf`; anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '专题图导出失败');
    } finally { setLoading(false); }
  }

  return <Button block loading={loading} icon={<FilePdfOutlined />} onClick={() => void exportPdf()}>导出专业专题图 PDF</Button>;
}
