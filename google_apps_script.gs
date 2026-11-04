// 將這份檔案完整取代 Google Sheet「擴充功能 → Apps Script」中的舊程式，
// 再從「部署 → 管理部署 → 編輯 → 新版本」更新原有 Web App 部署。

function jsonResponse_(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
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
    var urlCell = sheet.getRange(row, 18);
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
  } catch (error) {
    return jsonResponse_({status: "error", message: "回寫失敗，請確認 Web App 權限與資料格式"});
  }
}
