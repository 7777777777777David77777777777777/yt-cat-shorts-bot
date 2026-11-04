const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function fixture() {
  const rows = Array.from({length: 9}, () => Array(18).fill(''));
  rows[7] = [
    'EP01', '連發中 (Sending)', 1, 'Watercolor', 'Mia', 'Mochi', 'Titan',
    'Narration 1', 'Action 1', 'Narration 2', 'Action 2',
    'Narration 3', 'Action 3', 'Narration 4', 'Action 4',
    'Real title', 'kitten, husky', '(等待 GitHub Actions 自動回填)',
  ];
  rows[8] = [...rows[7]];
  rows[8][0] = 'EP02';
  const sheet = {
    getDataRange: () => ({getValues: () => rows.map(row => [...row])}),
    getLastRow: () => rows.length,
    getRange(row, column) {
      assert.ok(row >= 1 && row <= rows.length && column >= 1 && column <= 18);
      return {
        getValue: () => rows[row - 1][column - 1],
        setValue: value => { rows[row - 1][column - 1] = value; },
      };
    },
  };
  const context = {
    SpreadsheetApp: {getActiveSpreadsheet: () => ({getSheets: () => [sheet]})},
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
  return {rows, context, payload, post(body = payload) {
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
