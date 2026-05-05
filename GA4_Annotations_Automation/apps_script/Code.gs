/**
 * GA4 Annotations — Phase 0/1 starter script
 * Replace PROPERTY_ID placeholders before running.
 */

function normalize(s) {
  if (s === undefined || s === null) return '';
  return String(s).toLowerCase().trim().replace(/\s+/g, ' ');
}

function buildTripletKey(source, medium, campaign) {
  return normalize(source) + '|' + normalize(medium) + '|' + normalize(campaign);
}

/**
 * Test Data API `runReport` for yesterday's sessions by campaign.
 * Replace PROPERTY_ID with the numeric property id prefixed by 'properties/'.
 */
function testRunReport() {
  var propertyId = 'properties/PROPERTY_ID'; // e.g. properties/123456789
  var url = 'https://analyticsdata.googleapis.com/v1beta/' + propertyId + ':runReport';
  var payload = {
    "dimensions":[{"name":"sessionSource"},{"name":"sessionMedium"},{"name":"sessionCampaignName"}],
    "metrics":[{"name":"sessions"}],
    "dateRanges":[{"startDate":"yesterday","endDate":"yesterday"}],
    "limit": 100000
  };
  var options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  };
  var resp = UrlFetchApp.fetch(url, options);
  Logger.log('HTTP ' + resp.getResponseCode());
  var text = resp.getContentText();
  Logger.log(text);
  try {
    var json = JSON.parse(text);
    if (json.rows) {
      var out = json.rows.map(function(r){
        var dims = (r.dimensionValues || []).map(function(d){ return d.value; });
        var mets = (r.metricValues || []).map(function(mv){ return mv.value; });
        return { source: dims[0]||'', medium: dims[1]||'', campaign: dims[2]||'', sessions: mets[0]||'0', key: buildTripletKey(dims[0], dims[1], dims[2]) };
      });
      Logger.log(JSON.stringify(out, null, 2));
    }
  } catch(e) {
    Logger.log('JSON parse error: ' + e);
  }
}

/**
 * Quick Admin API permission test (GET property). Replace PROPERTY_ID with numeric id.
 * This verifies the script's Admin API access without creating resources.
 */
function testAdminApiGetProperty() {
  var propertyNumericId = 'PROPERTY_ID'; // numeric id only, e.g. 123456789
  var url = 'https://analyticsadmin.googleapis.com/v1beta/properties/' + propertyNumericId;
  var options = {
    method: 'get',
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  };
  var resp = UrlFetchApp.fetch(url, options);
  Logger.log('HTTP ' + resp.getResponseCode());
  Logger.log(resp.getContentText());
}

/**
 * Read `Config` sheet and return array of config objects.
 */
function readConfigSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName('Config');
  if (!sheet) {
    throw new Error('Config sheet not found. Create a sheet named "Config" with headers.');
  }
  var values = sheet.getDataRange().getValues();
  if (values.length < 2) return [];
  var headers = values[0];
  var rows = [];
  for (var i = 1; i < values.length; i++) {
    var row = {};
    for (var j = 0; j < headers.length; j++) {
      row[headers[j]] = values[i][j];
    }
    rows.push(row);
  }
  return rows;
}

/**
 * Fetch report for a numeric property id and return normalized triplets above threshold.
 */
function fetchReportForPropertyNumeric(propertyNumericId, minSessions) {
  var propertyId = 'properties/' + propertyNumericId;
  var url = 'https://analyticsdata.googleapis.com/v1beta/' + propertyId + ':runReport';
  var payload = {
    "dimensions": [{"name": "sessionSource"}, {"name": "sessionMedium"}, {"name": "sessionCampaignName"}],
    "metrics": [{"name": "sessions"}],
    "dateRanges": [{"startDate": "yesterday", "endDate": "yesterday"}],
    "limit": 100000
  };
  var options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  };
  var resp = UrlFetchApp.fetch(url, options);
  var code = resp.getResponseCode();
  if (code !== 200) {
    Logger.log('Data API HTTP ' + code + ': ' + resp.getContentText());
    return [];
  }
  var text = resp.getContentText();
  var out = [];
  try {
    var json = JSON.parse(text);
    if (json.rows) {
      for (var i = 0; i < json.rows.length; i++) {
        var r = json.rows[i];
        var dims = (r.dimensionValues || []).map(function(d) { return d.value; });
        var mets = (r.metricValues || []).map(function(mv) { return mv.value; });
        var source = dims[0] || '';
        var medium = dims[1] || '';
        var campaign = dims[2] || '';
        if (!campaign || campaign === '(not set)') continue;
        var sessions = Number(mets[0] || 0);
        if (sessions < (minSessions || 0)) continue;
        var key = buildTripletKey(source, medium, campaign);
        out.push({ source: source, medium: medium, campaign: campaign, sessions: sessions, key: key });
      }
    }
  } catch (e) {
    Logger.log('JSON parse error: ' + e + '\n' + text);
  }
  return out;
}

/**
 * Write normalized API output to a debug sheet for inspection.
 */
function writeDebugApiOutput(propertyNumericId, rows) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var name = 'Debug - API Output ' + propertyNumericId;
  var sheet = ss.getSheetByName(name);
  if (!sheet) sheet = ss.insertSheet(name);
  sheet.clearContents();
  var headers = ['property_id','source','medium','campaign','sessions','triplet_key'];
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  if (rows.length === 0) return;
  var out = rows.map(function(r) { return [propertyNumericId, r.source, r.medium, r.campaign, r.sessions, r.key]; });
  sheet.getRange(2, 1, out.length, out[0].length).setValues(out);
}

/**
 * Main runner for Phase 1: read `Config`, fetch reports for active properties, and write debug output.
 */
function runDailyFetch() {
  var configs = readConfigSheet();
  if (configs.length === 0) {
    Logger.log('No config rows found. Create a `Config` sheet with property_id and active columns.');
    return;
  }
  for (var i = 0; i < configs.length; i++) {
    var cfg = configs[i];
    var active = String(cfg.active || '').toLowerCase();
    if (active !== 'true' && active !== 'yes') continue;
    var propertyNumeric = String(cfg.property_id).trim();
    if (!propertyNumeric) {
      Logger.log('Skipping config row with empty property_id at index: ' + (i+2));
      continue;
    }
    var minSessions = Number(cfg.min_sessions) || 50;
    var rows = fetchReportForPropertyNumeric(propertyNumeric, minSessions);
    writeDebugApiOutput(propertyNumeric, rows);
    Logger.log('Property ' + propertyNumeric + ': found ' + rows.length + ' triplets above ' + minSessions + ' sessions');
  }
}

/**
 * Read the `Campaign log` sheet into an object map for fast lookups.
 * Returns: { sheet, headers, rows, map }
 * - map keys are `property_id + '|' + triplet_key` => { rowIndex, valuesObj }
 */
function readCampaignLogSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName('Campaign log');
  if (!sheet) return { sheet: null, headers: [], rows: [], map: {} };
  var values = sheet.getDataRange().getValues();
  if (values.length === 0) return { sheet: sheet, headers: [], rows: [], map: {} };
  var headers = values[0].map(function(h){ return String(h); });
  var rows = values.slice(1);
  var map = {};
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    var obj = {};
    for (var j = 0; j < headers.length; j++) obj[headers[j]] = row[j];
    var key = String(obj.property_id || '') + '|' + String(obj.triplet_key || '');
    map[key] = { rowIndex: i + 2, valuesObj: obj };
  }
  return { sheet: sheet, headers: headers, rows: rows, map: map };
}

/**
 * Bulk update the `Campaign log` sheet given an array of update objects.
 * Each update: { property_id, triplet_key, source, medium, campaign, first_seen_date, last_seen_date, signal_type, annotation_id, annotated_at, session_count }
 * This function performs in-memory updates and writes the full table back in a single setValues call.
 */
function bulkUpdateCampaignLog(updates) {
  if (!updates || updates.length === 0) return;
  var state = readCampaignLogSheet();
  var sheet = state.sheet;
  var expected = ['property_id','triplet_key','source','medium','campaign','first_seen_date','last_seen_date','signal_type','annotation_id','annotated_at','session_count'];
  var headers = state.headers && state.headers.length ? state.headers : expected;

  // Build list of existing rows as objects
  var existing = [];
  for (var i = 0; i < state.rows.length; i++) {
    var r = state.rows[i];
    var obj = {};
    for (var j = 0; j < headers.length; j++) obj[headers[j]] = r[j] === undefined ? '' : r[j];
    existing.push(obj);
  }

  // Helper to find index in existing by property_id+triplet_key
  function findIndex(propId, triplet) {
    for (var k = 0; k < existing.length; k++) {
      if (String(existing[k].property_id || '') + '|' + String(existing[k].triplet_key || '') === String(propId) + '|' + String(triplet)) return k;
    }
    return -1;
  }

  // Apply updates
  for (var u = 0; u < updates.length; u++) {
    var up = updates[u];
    var idx = findIndex(up.property_id, up.triplet_key);
    if (idx === -1) {
      // create new row object using expected columns
      var newRow = {};
      for (var h = 0; h < expected.length; h++) newRow[expected[h]] = '';
      newRow.property_id = up.property_id;
      newRow.triplet_key = up.triplet_key;
      newRow.source = up.source || '';
      newRow.medium = up.medium || '';
      newRow.campaign = up.campaign || '';
      newRow.first_seen_date = up.first_seen_date || '';
      newRow.last_seen_date = up.last_seen_date || newRow.first_seen_date || Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
      newRow.signal_type = up.signal_type || '';
      newRow.annotation_id = up.annotation_id || '';
      newRow.annotated_at = up.annotated_at || '';
      newRow.session_count = up.session_count || '';
      existing.push(newRow);
    } else {
      // update existing row fields
      var rowObj = existing[idx];
      rowObj.last_seen_date = up.last_seen_date || up.first_seen_date || Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
      if (up.signal_type) rowObj.signal_type = up.signal_type;
      if (up.annotation_id) rowObj.annotation_id = up.annotation_id;
      if (up.annotated_at) rowObj.annotated_at = up.annotated_at;
      if (up.session_count !== undefined) rowObj.session_count = up.session_count;
    }
  }

  // Ensure header order
  var finalHeaders = expected.slice();

  // Build values array to write
  var valuesOut = [];
  for (var e = 0; e < existing.length; e++) {
    var rowArr = [];
    for (var hh = 0; hh < finalHeaders.length; hh++) rowArr.push(existing[e][finalHeaders[hh]] || '');
    valuesOut.push(rowArr);
  }

  // Clear sheet and write headers + values
  if (!sheet) {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    sheet = ss.insertSheet('Campaign log');
  }
  sheet.clearContents();
  sheet.getRange(1, 1, 1, finalHeaders.length).setValues([finalHeaders]);
  if (valuesOut.length > 0) sheet.getRange(2, 1, valuesOut.length, finalHeaders.length).setValues(valuesOut);
}

/**
 * Create an annotation via the Analytics Admin API for a given property.
 * annotation: { annotationDate (yyyy-mm-dd), title, body, color }
 * Returns the API response object on success, or null on failure.
 */
function createAnnotation(propertyNumericId, annotation) {
  var url = 'https://analyticsadmin.googleapis.com/v1beta/properties/' + propertyNumericId + '/annotations';
  var body = {};
  if (annotation.annotationDate) body.annotationDate = annotation.annotationDate;
  if (annotation.title) body.title = annotation.title;
  if (annotation.body) body.body = annotation.body;
  if (annotation.color) body.color = annotation.color;
  var options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(body),
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  };
  try {
    var resp = UrlFetchApp.fetch(url, options);
    var code = resp.getResponseCode();
    var txt = resp.getContentText();
    Logger.log('Annotation write HTTP ' + code + ': ' + txt);
    if (code >= 200 && code < 300) {
      return JSON.parse(txt);
    }
    return null;
  } catch (e) {
    Logger.log('Annotation write error: ' + e);
    return null;
  }
}


