// 使用工作区统一 artifact-tool 生成并渲染 Phase 2 Excel 导入模板。
import fs from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { SpreadsheetFile, Workbook } from 'file:///C:/Users/13104/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';

const outputDir = new URL('../docs/templates/', import.meta.url);
const previewDir = new URL('../docs/templates/previews/', import.meta.url);
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const templates = [
  {
    resource: 'rivers',
    title: '河道导入模板',
    headers: ['code', 'name', 'length', 'level', 'status', 'description', 'coordinates_json'],
    sample: ['SAMPLE-RIVER-001', '示例河道（导入前请删除）', 12000, 'main', 'active', 'CGCS2000 / EPSG:4490', '[[120.0,30.2],[120.1,30.25]]'],
    widths: [22, 28, 14, 14, 14, 30, 48],
    validations: [{ range: 'D2:D500', values: ['main', 'tributary', 'channel'] }, { range: 'E2:E500', values: ['active', 'inactive', 'planned'] }],
    notes: [
      ['code', '版本内唯一的河道编码', '必填', 'SAMPLE-RIVER-001'],
      ['length', '河道总长度，单位 m，必须大于等于 0', '必填', '12000'],
      ['coordinates_json', 'LineString 坐标数组；每点为 [经度,纬度]', '必填', '[[120.0,30.2],[120.1,30.25]]'],
    ],
  },
  {
    resource: 'cross_sections',
    title: '横断面导入模板',
    headers: ['river_code', 'section_code', 'section_name', 'station', 'points_json', 'roughness', 'elevation_min', 'survey_date', 'longitude', 'latitude'],
    sample: ['DEMO-RIVER-A', 'SAMPLE-CS-001', '示例横断面（导入前请删除）', 1000, '[[0,10],[5,8],[10,10]]', 0.035, 8, '2026-08-11', 120.1, 30.25],
    widths: [20, 20, 28, 14, 42, 14, 16, 16, 16, 16],
    notes: [
      ['river_code', '同一数据版本中已存在的河道编码', '必填', 'DEMO-RIVER-A'],
      ['station', '沿河桩号，单位 m，不得超过河道长度', '必填', '1000'],
      ['points_json', '横距严格递增的 [横距,高程] 数组，至少 3 点', '必填', '[[0,10],[5,8],[10,10]]'],
      ['roughness', '曼宁糙率，必须大于 0', '必填', '0.035'],
    ],
  },
  {
    resource: 'gates',
    title: '闸门导入模板',
    headers: ['river_code', 'gate_code', 'name', 'gate_type', 'opening_direction', 'control_mode', 'width', 'height', 'max_flow', 'bottom_elevation', 'status', 'longitude', 'latitude'],
    sample: ['DEMO-RIVER-A', 'SAMPLE-GATE-001', '示例闸门（导入前请删除）', '节制闸', 'vertical', 'local', 10, 5, 60, 4.8, 'offline', 120.1, 30.25],
    widths: [20, 20, 28, 16, 20, 18, 12, 12, 16, 20, 16, 16, 16],
    validations: [{ range: 'E2:E500', values: ['vertical', 'horizontal'] }, { range: 'F2:F500', values: ['local', 'remote', 'automatic'] }, { range: 'K2:K500', values: ['online', 'offline', 'maintenance', 'fault'] }],
    notes: [
      ['gate_code', '版本内唯一的闸门编码', '必填', 'SAMPLE-GATE-001'],
      ['width / height', '闸孔宽度、高度，单位 m，必须大于 0', '必填', '10 / 5'],
      ['max_flow', '设计最大过流能力，单位 m³/s', '必填', '60'],
    ],
  },
  {
    resource: 'pumps',
    title: '泵站导入模板',
    headers: ['river_code', 'pump_code', 'name', 'design_flow', 'head', 'power', 'efficiency_curve_json', 'control_mode', 'status', 'longitude', 'latitude'],
    sample: ['DEMO-RIVER-A', 'SAMPLE-PUMP-001', '示例泵站（导入前请删除）', 50, 6, 1200, '[[0,0],[0.5,0.78],[1,0.84]]', 'local', 'offline', 120.1, 30.25],
    widths: [20, 20, 28, 18, 12, 16, 42, 18, 16, 16, 16],
    validations: [{ range: 'H2:H500', values: ['local', 'remote', 'automatic'] }, { range: 'I2:I500', values: ['online', 'offline', 'maintenance', 'fault'] }],
    notes: [
      ['pump_code', '版本内唯一的泵站编码', '必填', 'SAMPLE-PUMP-001'],
      ['design_flow / head / power', '设计流量、扬程、功率，均不得为负', '必填', '50 / 6 / 1200'],
      ['efficiency_curve_json', '至少两个 [流量比,效率] 点', '必填', '[[0,0],[0.5,0.78],[1,0.84]]'],
    ],
  },
];

for (const definition of templates) {
  const workbook = Workbook.create();
  const data = workbook.worksheets.add('导入数据');
  const notes = workbook.worksheets.add('填写说明');
  data.showGridLines = false;
  notes.showGridLines = false;
  data.freezePanes.freezeRows(1);
  data.getRangeByIndexes(0, 0, 2, definition.headers.length).values = [definition.headers, definition.sample];
  data.getRangeByIndexes(0, 0, 1, definition.headers.length).format = {
    fill: '#0F5162',
    font: { bold: true, color: '#FFFFFF' },
    borders: { preset: 'all', style: 'thin', color: '#4D8490' },
    wrapText: true,
  };
  data.getRangeByIndexes(1, 0, 1, definition.headers.length).format = {
    fill: '#E8F6F7',
    font: { color: '#315866', italic: true },
    borders: { preset: 'all', style: 'thin', color: '#B7D5DA' },
    wrapText: true,
  };
  definition.widths.forEach((width, index) => {
    data.getRangeByIndexes(0, index, 500, 1).format.columnWidth = width;
  });
  data.getRange('A1:Z500').format.rowHeight = 22;
  data.getRangeByIndexes(0, 0, 2, definition.headers.length).format.rowHeight = 34;
  const table = data.tables.add(data.getRangeByIndexes(0, 0, 2, definition.headers.length), true, `${definition.resource.replace('_', '')}ImportTable`);
  table.style = 'TableStyleMedium2';
  for (const validation of definition.validations ?? []) {
    data.getRange(validation.range).dataValidation = { rule: { type: 'list', values: validation.values } };
  }

  notes.getRange('A1:D1').merge();
  notes.getRange('A1').values = [[`大禹·天工 Phase 2｜${definition.title}`]];
  notes.getRange('A1:D1').format = { fill: '#083A4A', font: { bold: true, color: '#FFFFFF', size: 16 }, rowHeight: 36 };
  notes.getRange('A3:D3').values = [['字段', '填写规则', '要求', '示例']];
  notes.getRangeByIndexes(3, 0, definition.notes.length, 4).values = definition.notes;
  notes.getRange('A3:D3').format = { fill: '#0F7A7A', font: { bold: true, color: '#FFFFFF' }, borders: { preset: 'all', style: 'thin', color: '#8FC4C6' } };
  notes.getRangeByIndexes(3, 0, definition.notes.length, 4).format = { borders: { preset: 'all', style: 'thin', color: '#C6DDE0' }, wrapText: true };
  notes.getRange('A9:D12').merge();
  notes.getRange('A9').values = [['使用说明：\n1. 导入时由页面选择数据版本，模板内不填写版本 ID。\n2. 第一行字段名不可修改；请删除示例行后填写正式数据。\n3. 坐标统一使用 CGCS2000（EPSG:4490），坐标顺序为 [经度,纬度]。\n4. 任一行错误时整批不写入，错误会定位到具体行号。']];
  notes.getRange('A9:D12').format = { fill: '#EEF7F7', font: { color: '#315866' }, wrapText: true, verticalAlignment: 'top', rowHeight: 25, borders: { preset: 'outside', style: 'thin', color: '#9FC9CC' } };
  notes.getRange('A:D').format.columnWidth = 26;
  notes.getRange('B:B').format.columnWidth = 52;
  notes.getRange('D:D').format.columnWidth = 44;
  notes.freezePanes.freezeRows(3);

  const inspection = await workbook.inspect({ kind: 'sheet,table,region', sheetId: '导入数据', range: `A1:${String.fromCharCode(64 + definition.headers.length)}4`, maxChars: 3000, tableMaxRows: 4, tableMaxCols: 14 });
  await fs.writeFile(new URL(`previews/phase2_${definition.resource}_inspect.txt`, outputDir), inspection.ndjson, 'utf8');
  const preview = await workbook.render({ sheetName: '导入数据', autoCrop: 'all', scale: 1.2, format: 'png' });
  await fs.writeFile(new URL(`phase2_${definition.resource}_template.png`, previewDir), new Uint8Array(await preview.arrayBuffer()));
  const notesPreview = await workbook.render({ sheetName: '填写说明', autoCrop: 'all', scale: 1.2, format: 'png' });
  await fs.writeFile(new URL(`phase2_${definition.resource}_notes.png`, previewDir), new Uint8Array(await notesPreview.arrayBuffer()));
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(fileURLToPath(new URL(`phase2_${definition.resource}_template.xlsx`, outputDir)));
}

console.log(`Generated ${templates.length} Phase 2 templates in ${outputDir.pathname}`);
