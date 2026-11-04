// 將這份檔案完整取代 Google Sheet「擴充功能 → Apps Script」中的舊程式，
// 再從「部署 → 管理部署 → 編輯 → 新版本」更新原有 Web App 部署。

var SCRIPT_VERSION = "r18-usage-v2";
var URL_COLUMN = 18;

function jsonResponse_(value) {
  value.script_version = SCRIPT_VERSION;
  value.url_column = URL_COLUMN;
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}

function withSheetLock_(operation) {
  var lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {
    return operation();
  } finally {
    lock.releaseLock();
  }
}

function doGet(e) {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = spreadsheet.getSheets()[0];
  // 這個網址可用來確認 GitHub 使用的 /exec 部署，不會產片或修改 Sheet。
  if (e && e.parameter && e.parameter.action === "status") {
    return jsonResponse_({status: "ok", spreadsheet_id: spreadsheet.getId(), sheet_id: sheet.getSheetId()});
  }
  var data = sheet.getDataRange().getValues();
  for (var i = 1; i < data.length; i++) {
    var epId = String(data[i][0]).trim();
    var status = String(data[i][1]).trim();
    var sentCount = parseInt(String(data[i][2]).split("/")[0], 10) || 0;
    if (/^EP\d+$/.test(epId) && status.indexOf("已完成") === -1 &&
        status.toLowerCase().indexOf("completed") === -1 && sentCount < 6) {
      return jsonResponse_({
        status: "ok",
        episode: {
          row_index: i + 1, id: epId, status: status, sent_count: sentCount,
          art_dna: data[i][3],
          char1_dna: data[i][4], char2_dna: data[i][5], char3_dna: data[i][6],
          s1_narration: data[i][7], s1_action: data[i][8],
          s2_narration: data[i][9], s2_action: data[i][10],
          s3_narration: data[i][11], s3_action: data[i][12],
          s4_narration: data[i][13], s4_action: data[i][14],
          title: data[i][15], tags: data[i][16]
        }
      });
    }
  }
  return jsonResponse_({status: "empty"});
}

function doPost(e) {
  try {
    return withSheetLock_(function() {
      var body = JSON.parse(e.postData.contents);
      var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
      var row = Number(body.row_index);
      var count = Number(body.new_sent_count);
      var target = Number(body.target_sends || 6);
      if (body.action !== "mark_sent" || !Number.isInteger(row) || row < 2 ||
          row > sheet.getLastRow() || !Number.isInteger(count) || count < 1 ||
          !Number.isInteger(target) || target < 1 || count > target) {
        return jsonResponse_({status: "error", message: "無效的回寫資料"});
      }
      if (String(sheet.getRange(row, 1).getValue()).trim() !== String(body.id).trim()) {
        return jsonResponse_({status: "error", message: "集數 ID 與回寫列不符"});
      }
      var youtubeUrl = String(body.youtube_url || "").trim();
      if (!/^https:\/\/(www\.)?youtube\.com\/shorts\/[A-Za-z0-9_-]+$/.test(youtubeUrl)) {
        return jsonResponse_({status: "error", message: "無效的 YouTube Shorts 網址"});
      }

      // 影片紀錄一律從 R 欄讀取，並寫回 R 欄；Q 欄 SEO 標籤不變。
      var urlCell = sheet.getRange(row, URL_COLUMN);
      var prevUrls = String(urlCell.getValue() || "").split(/\r?\n/)
        .filter(function(line) { return line.trim() && line.indexOf("等待") === -1; })
        .join("\n");
      // 網路重送同一支影片時，不重複追加紀錄。
      if (prevUrls.indexOf(youtubeUrl) !== -1) {
        return jsonResponse_({status: "updated", duplicate: true});
      }
      var usageSummary = String(body.usage_summary || "產圖 token：未提供").replace(/[\r\n]+/g, " ");
      var entry = "[" + count + "/" + target + "] " + youtubeUrl + " | " + usageSummary;
      urlCell.setValue((prevUrls ? prevUrls + "\n" : "") + entry);
      sheet.getRange(row, 3).setValue(count);
      sheet.getRange(row, 2).setValue(count >= target ? "已完成 (Completed)" : "連發中 (Sending)");
      return jsonResponse_({status: "updated"});
    });
  } catch (error) {
    return jsonResponse_({status: "error", message: "回寫失敗，請確認 Web App 權限與資料格式"});
  }
}

// 在 Apps Script 編輯器手動執行一次；把舊 Q 欄影片紀錄搬到 R 欄。
// 僅搬移整行的 Shorts 網址紀錄，保留標籤、發送次數與狀態，不會發布影片。
function repairLegacyUrlRecords() {
  return withSheetLock_(function() {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
    var report = {rows_updated: 0, records_moved: 0, records_removed_from_q: 0};
    var recordPattern = /^(?:\[\d+\/\d+\]\s*)?(https:\/\/(?:www\.)?youtube\.com\/shorts\/[A-Za-z0-9_-]+)(?:\s*\|.*)?$/;
    for (var row = 2; row <= sheet.getLastRow(); row++) {
      if (!/^EP\d+$/.test(String(sheet.getRange(row, 1).getValue()).trim())) continue;
      var tagCell = sheet.getRange(row, 17);
      var remaining = [];
      var records = [];
      String(tagCell.getValue() || "").split(/\r?\n/).forEach(function(line) {
        var match = line.trim().match(recordPattern);
        if (match) records.push({text: line.trim(), url: match[1]});
        else remaining.push(line);
      });
      if (!records.length) continue;
      var urlCell = sheet.getRange(row, URL_COLUMN);
      var previous = String(urlCell.getValue() || "").split(/\r?\n/)
        .filter(function(line) { return line.trim() && line.indexOf("等待") === -1; });
      var knownUrls = new Set(previous.map(function(line) {
        var match = line.trim().match(recordPattern);
        return match ? match[1] : null;
      }).filter(Boolean));
      records.forEach(function(record) {
        if (!knownUrls.has(record.url)) {
          previous.push(record.text);
          knownUrls.add(record.url);
          report.records_moved++;
        }
      });
      // 先保存到 R，成功後才從 Q 移除，避免搬移失敗時遺失原始紀錄。
      urlCell.setValue(previous.join("\n"));
      tagCell.setValue(remaining.join("\n").trim());
      report.rows_updated++;
      report.records_removed_from_q += records.length;
    }
    console.log("舊網址修復結果：" + JSON.stringify(report));
    return report;
  });
}
