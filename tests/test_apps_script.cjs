const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function fixture(sixScenes = false) {
  const rows = Array.from({length: 9}, () => Array(sixScenes ? 22 : 18).fill(''));
  rows[6] = ['集數 ID', '發佈狀態', '已發送次數', '劇本類型', '角色 1', '角色 2', '角色 3',
    '第 1 幕：英文台詞', '第 1 幕：畫面動作', '第 2 幕：英文台詞', '第 2 幕：畫面動作',
    '第 3 幕：英文台詞', '第 3 幕：畫面動作', '第 4 幕：英文台詞', '第 4 幕：畫面動作',
    ...(sixScenes ? ['第 5 幕：英文台詞', '第 5 幕：畫面動作', '第 6 幕：英文台詞', '第 6 幕：畫面動作'] : []),
    'YouTube 爆款標題', 'SEO 標籤 (Tags)', '已發佈 YouTube 網址紀錄'];
  rows[7] = [
    'EP01', '連發中 (Sending)', 1, 'Watercolor', 'Mia', 'Mochi', 'Titan',
    'Narration 1', 'Action 1', 'Narration 2', 'Action 2',
    'Narration 3', 'Action 3', 'Narration 4', 'Action 4',
    ...(sixScenes ? ['Narration 5', 'Action 5', 'Narration 6', 'Action 6'] : []),
    'Real title', 'kitten, husky', '(等待 GitHub Actions 自動回填)',
  ];
  rows[8] = [...rows[7]];
  rows[8][0] = 'EP02';
  const sheet = {
    getSheetId: () => 0,
    getDataRange: () => ({getValues: () => rows.map(row => [...row])}),
    getLastRow: () => rows.length,
    getRange(row, column) {
      assert.ok(row >= 1 && row <= rows.length && column >= 1 && column <= (sixScenes ? 22 : 18));
      return {
        getValue: () => rows[row - 1][column - 1],
        setValue: value => { rows[row - 1][column - 1] = value; },
      };
    },
  };
  let locked = false;
  const context = {
    SpreadsheetApp: {getActiveSpreadsheet: () => ({getSheets: () => [sheet], getId: () => 'test-spreadsheet'})},
    LockService: {getScriptLock: () => ({
      waitLock() { assert.equal(locked, false); locked = true; },
      releaseLock() { assert.equal(locked, true); locked = false; },
    })},
    console: {log() {}},
    ContentService: {
      MimeType: {JSON: 'application/json'},
      createTextOutput: text => ({text, setMimeType() { return this; }}),
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'google_apps_script.gs'), 'utf8'), context);
  const payload = {
    action: 'mark_sent', row_index: 8, id: 'EP01', new_sent_count: 2, target_sends: 6,
    youtube_url: 'https://youtube.com/shorts/testVideo01',
    usage_summary: '產圖 token：4,000；成功圖片：4 張；API 請求：4 次；模型：gemini-2.5-flash-image',
  };
  return {rows, context, payload, sheet, post(body = payload) {
    return JSON.parse(context.doPost({postData: {contents: JSON.stringify(body)}}).text);
  }};
}

test('doGet returns G character 3, H:O scenes, P title and Q tags', () => {
  const {context} = fixture();
  const result = JSON.parse(context.doGet({}).text);
  assert.equal(result.status, 'ok');
  assert.equal(result.episode.row_index, 8);
  assert.equal(result.episode.char3_dna, 'Titan');
  for (let i = 1; i <= 4; i++) {
    assert.equal(result.episode[`s${i}_narration`], `Narration ${i}`);
    assert.equal(result.episode[`s${i}_action`], `Action ${i}`);
  }
  assert.equal(result.episode.title, 'Real title');
  assert.equal(result.episode.tags, 'kitten, husky');
});

test('URL plus token summary is written to R; Q tags stay intact', () => {
  const {rows, post, payload} = fixture();
  const tags = rows[7][16];
  assert.equal(post().status, 'updated');
  assert.equal(rows[7][16], tags);
  assert.equal(rows[7][17], `[2/6] ${payload.youtube_url} | ${payload.usage_summary}`);
  assert.equal(rows[7][2], 2);
  assert.equal(rows[7][1], '連發中 (Sending)');
});

test('previous R records are kept and Q is never copied into R', () => {
  const {rows, post, payload} = fixture();
  const old = '[1/6] https://youtube.com/shorts/previous001 | 產圖 token：未提供';
  rows[7][17] = old;
  post();
  assert.equal(rows[7][17], `${old}\n[2/6] ${payload.youtube_url} | ${payload.usage_summary}`);
  assert.ok(!rows[7][17].includes('kitten, husky'));
});

test('missing usage is marked unavailable rather than zero', () => {
  const {rows, post, payload} = fixture();
  delete payload.usage_summary;
  post();
  assert.ok(rows[7][17].endsWith(' | 產圖 token：未提供'));
});

test('retrying the same video does not duplicate the record', () => {
  const {rows, post} = fixture();
  post();
  const previous = rows[7][17];
  assert.equal(post().duplicate, true);
  assert.equal(rows[7][17], previous);
});

test('the sixth send marks an episode complete', () => {
  const {rows, post, payload} = fixture();
  post({...payload, new_sent_count: 6});
  assert.equal(rows[7][1], '已完成 (Completed)');
  assert.equal(rows[7][2], 6);
  assert.ok(rows[7][17].startsWith('[6/6]'));
});

test('wrong episode, invalid row and invalid URL leave all cells unchanged', () => {
  for (const changes of [{id: 'EP99'}, {row_index: 0}, {row_index: 99}, {youtube_url: ''}]) {
    const {rows, post, payload} = fixture();
    const original = JSON.stringify(rows);
    assert.equal(post({...payload, ...changes}).status, 'error');
    assert.equal(JSON.stringify(rows), original);
  }
});

test('completed episodes are skipped and exhausted queues return empty', () => {
  const {rows, context} = fixture();
  rows[7][1] = 'completed';
  assert.equal(JSON.parse(context.doGet({}).text).episode.id, 'EP02');
  rows[8][2] = 6;
  assert.equal(JSON.parse(context.doGet({}).text).status, 'empty');
});

test('status endpoint identifies deployed script and destination without touching cells', () => {
  const {rows, context} = fixture();
  const original = JSON.stringify(rows);
  const result = JSON.parse(context.doGet({parameter: {action: 'status'}}).text);
  assert.equal(result.script_version, 'six-scenes-usage-v3');
  assert.equal(result.url_column, 18);
  assert.equal(result.spreadsheet_id, 'test-spreadsheet');
  assert.equal(result.sheet_id, 0);
  assert.equal(JSON.stringify(rows), original);
});

test('POST acknowledgement includes deployment version and R column', () => {
  const {post} = fixture();
  const result = post();
  assert.equal(result.script_version, 'six-scenes-usage-v3');
  assert.equal(result.url_column, 18);
});

test('six-scene GET reads H:S scenes and T/U title/tags; reports V writeback', () => {
  const {context} = fixture(true);
  const result = JSON.parse(context.doGet({}).text);
  assert.equal(result.url_column, 22);
  for (let i = 1; i <= 6; i++) {
    assert.equal(result.episode[`s${i}_narration`], `Narration ${i}`);
    assert.equal(result.episode[`s${i}_action`], `Action ${i}`);
  }
  assert.equal(result.episode.title, 'Real title');
  assert.equal(result.episode.tags, 'kitten, husky');
});

test('six-scene POST preserves H:U and appends usage to V, including retries', () => {
  const {rows, context, post, payload} = fixture(true);
  const script = rows[7].slice(3, 21);
  rows[7][21] = '[1/6] https://youtube.com/shorts/previous001';
  const result = post();
  assert.equal(result.status, 'updated');
  assert.equal(result.url_column, 22);
  assert.deepEqual(rows[7].slice(3, 21), script);
  assert.equal(rows[7][21], `[1/6] https://youtube.com/shorts/previous001\n[2/6] ${payload.youtube_url} | ${payload.usage_summary}`);
  const previous = rows[7][21];
  assert.equal(post().duplicate, true);
  assert.equal(rows[7][21], previous);
  const status = JSON.parse(context.doGet({parameter: {action: 'status'}}).text);
  assert.equal(status.scene_capacity, 6);
  assert.equal(status.url_column, 22);
});

test('legacy URL repair cannot move Q/R scene content in the six-scene layout', () => {
  const {rows, context} = fixture(true);
  const previous = JSON.stringify(rows);
  assert.throws(() => context.repairLegacyUrlRecords(), /只適用舊四幕/);
  assert.equal(JSON.stringify(rows), previous);
});

test('invalid headers stop writeback before any cell is changed', () => {
  const {rows, post} = fixture(true);
  rows[6][19] = 'Unknown column';
  const previous = JSON.stringify(rows);
  assert.equal(post().status, 'error');
  assert.equal(JSON.stringify(rows), previous);
});

test('repair moves historical Q links to R and preserves SEO tags and progress', () => {
  const {rows, context} = fixture();
  const links = Array.from({length: 4}, (_, i) => `[${i + 1}/6] https://youtube.com/shorts/oldVideo00${i}`);
  rows[7][16] += '\n\n' + links.join('\n');
  const count = rows[7][2];
  const status = rows[7][1];
  const report = context.repairLegacyUrlRecords();
  assert.equal(report.rows_updated, 1);
  assert.equal(report.records_moved, 4);
  assert.equal(rows[7][16], 'kitten, husky');
  assert.equal(rows[7][17], links.join('\n'));
  assert.equal(rows[7][2], count);
  assert.equal(rows[7][1], status);
  const repaired = JSON.stringify(rows);
  assert.equal(context.repairLegacyUrlRecords().rows_updated, 0);
  assert.equal(JSON.stringify(rows), repaired);
});

test('repair deduplicates an existing R link and keeps its token details', () => {
  const {rows, context} = fixture();
  const url = 'https://youtube.com/shorts/oldVideo001';
  rows[7][16] += `\n[1/6] ${url}`;
  rows[7][17] = `[1/6] ${url} | 產圖 token：1,200`;
  const previous = rows[7][17];
  const report = context.repairLegacyUrlRecords();
  assert.equal(report.records_moved, 0);
  assert.equal(report.records_removed_from_q, 1);
  assert.equal(rows[7][16], 'kitten, husky');
  assert.equal(rows[7][17], previous);
});

test('repair preserves unrelated text and ignores non-episode rows', () => {
  const {rows, context} = fixture();
  rows[7][16] += '\nNotes with https://youtube.com/shorts/reference01 in a sentence';
  rows[5][16] = '[1/6] https://youtube.com/shorts/headerVideo';
  const original = JSON.stringify(rows);
  assert.equal(context.repairLegacyUrlRecords().rows_updated, 0);
  assert.equal(JSON.stringify(rows), original);
});

test('if saving R fails, repair leaves original Q links intact and releases the lock', () => {
  const {rows, context, sheet, post} = fixture();
  rows[7][16] += '\n[1/6] https://youtube.com/shorts/oldVideo001';
  const original = rows[7][16];
  const getRange = sheet.getRange;
  sheet.getRange = (row, column) => {
    const range = getRange(row, column);
    if (column === 18) range.setValue = () => { throw new Error('simulated Sheet write failure'); };
    return range;
  };
  assert.throws(() => context.repairLegacyUrlRecords(), /simulated Sheet write failure/);
  assert.equal(rows[7][16], original);
  sheet.getRange = getRange;
  assert.equal(post().status, 'updated');
});
