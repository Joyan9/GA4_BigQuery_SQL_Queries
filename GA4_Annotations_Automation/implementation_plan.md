
## Sheet architecture 

**`Config` tab**

| Column | Notes |
|---|---|
| `property_id` | GA4 property ID, numeric only (no "properties/" prefix — add it in script) |
| `property_name` | Human label, for run log readability |
| `min_sessions` | Floor for annotation trigger. Recommend default 50 |
| `reactivation_days` | Days of absence before treating a return as reactivation. Recommend 30 |
| `lookback_days` | How far back to check on first run / backfill. Recommend 90 |
| `active` | TRUE/FALSE — lets you pause a property without deleting config |
| `last_run` | Script writes here after each execution. Useful for debugging |

Support multiple rows — one per property. The script loops through active rows.

**`Campaign log` tab**

| Column | Notes |
|---|---|
| `property_id` | Ties rows to a property |
| `triplet_key` | Normalised `source|medium|campaign` (lowercased, trimmed) — this is the dedup key |
| `source` | Raw value from API |
| `medium` | Raw value |
| `campaign` | Raw value |
| `first_seen_date` | Actual `event_date` of first appearance, not run date |
| `last_seen_date` | Updated on every run — critical for reactivation detection |
| `signal_type` | `new_launch`, `reactivation`, `creative_rotation` |
| `annotation_id` | Returned by the Admin API — store this, you may need it for updates/deletes |
| `annotated_at` | Timestamp of when the script wrote the annotation |
| `session_count` | Sessions on first-seen day — useful for auditing threshold decisions |

The `triplet_key` being a normalised composite is the most important design decision here. Without normalisation, `Google / cpc / Brand_DE` and `google / CPC / brand_de` look like two different campaigns. Lowercase + trim everything before generating this key.

**`Run log` tab**

Simple append-only log: `timestamp`, `property_id`, `status` (success/error), `new_annotations`, `reactivations`, `error_message`. This is what you check when something looks wrong.

---

## Implementation plan

### Phase 0 — API enablement and auth (half a day)

Enable **Google Analytics Data API** and **Google Analytics Admin API** in the GCP project tied to your Apps Script. This is the step people forget, and the error message is not always clear when you skip it.

Apps Script OAuth scopes to declare in `appsscript.json`:
- `https://www.googleapis.com/auth/analytics.readonly` — for Data API
- `https://www.googleapis.com/auth/analytics.edit` — for Admin API (annotation writes)
- `https://www.googleapis.com/auth/spreadsheets` — for sheet read/write

**Consequence of getting auth wrong**: the script runs, appears to succeed, writes nothing, and logs nothing useful. Test each API call in isolation with a hardcoded property ID before wiring everything together.

---

### Phase 1 — Data fetch layer (1–2 days)

Call the GA4 Data API (`runReport`) to pull yesterday's session data by campaign dimensions.

Dimensions: `sessionSource`, `sessionMedium`, `sessionCampaignName`
Metric: `sessions`
Date range: yesterday to yesterday (single day, avoids sampling almost entirely)

**Filtering decisions with real consequences:**

Filter out `(not set)` and `(direct) / (none) / (not set)` triplets before any further processing. These will always appear as the largest "campaigns" and would generate noise on every run. Also filter `medium == "organic"` if you only want paid/owned channel campaign signals — that's a config-level decision worth exposing.

The `sessionCampaignName` dimension returns `(not set)` for sessions where no `utm_campaign` was present. A common mistake is treating a medium appearing for the first time as a campaign launch — it isn't. The triplet must have a real campaign value to be meaningful.

**Normalisation step** — after fetching, run every value through:
```
toLowerCase().trim().replace(/\s+/g, ' ')
```
Generate `triplet_key = source + '|' + medium + '|' + campaign`. This is what you look up in the campaign log.

---

### Phase 2 — Signal detection (1 day)

Load the campaign log into memory as a JS object keyed by `property_id + triplet_key` — don't query the sheet row-by-row in a loop, that's slow and hits Apps Script quota.

For each row from the API response (above the min sessions threshold):

- **Key not found in log** → `new_launch`
- **Key found, `last_seen_date` is within reactivation window** → skip (already annotated, still active)
- **Key found, `last_seen_date` is older than `reactivation_days`** → `reactivation`

`creative_rotation` is the trickiest signal. You need a separate log keyed on `source|medium|campaign` (without content/term) that tracks known `utm_content` values. If the triplet is known but a new `content` value appears, that's rotation. This is Phase 2b — get the first two signals working first before adding this complexity.

**An important consequence**: if your `last_seen_date` isn't updated reliably, reactivation logic breaks. The update must happen on every run, even for campaigns that don't generate a new annotation. This means Phase 4 (state management) has to update `last_seen_date` for *all* seen triplets, not just new ones.

---

### Phase 3 — Annotation formatting and write (1 day)

Title format (stay well under 255 chars):

- New launch: `🟢 New campaign: {campaign} via {source} / {medium}`
- Reactivation: `🔁 Campaign reactivated: {campaign} via {source} / {medium}`
- Rotation: `🔄 New creative: {content} — {campaign} via {source}`

Use the GA4 annotation color field to visually encode signal type — new = GREEN, reactivation = ORANGE, rotation = BLUE. This makes the GA4 timeline scannable at a glance.

The `annotationDate` field in the API should be set to `first_seen_date` (the actual event date from the API response), not today. This is critical — annotating today's date for a campaign that launched yesterday puts the marker in the wrong place.

Write one annotation at a time. Wrap each call in a try-catch. If the annotation write fails, **do not update the campaign log** for that row — let the next run retry it. Failing silently and marking it as done is the worst outcome.

---

### Phase 4 — State management (half a day)

After a successful run:
1. For new triplets: append to campaign log with all fields
2. For all seen triplets (new or existing): update `last_seen_date`
3. Append to run log regardless of outcome

Do bulk sheet writes — collect all updates in arrays, then write once with `setValues()`. Row-by-row writes are slow and chew through Apps Script execution time and quota.

**Consequence of not doing this**: a 500-campaign property with row-by-row writes could hit the 6-minute execution limit. Bulk reads + in-memory processing + bulk writes keeps a typical run well under 30 seconds.

---

### Phase 5 — Trigger, failure handling, and observability (1 day)

Set a **time-based trigger** at 09:00 user timezone — the GA4 BQ/Data API export is typically complete by 07:00–08:00 UTC for the previous day. Give it a buffer.

**Email on failure** — Apps Script has `MailApp.sendEmail()`. If any unhandled error propagates, catch it at the top level, write to run log, and send a notification. Silent failures are the primary operational risk with Apps Script deployments.

Add a **manual run button** via a custom menu (`onOpen` function adds a menu item). This is non-negotiable — you will need to test runs, debug client configs, and trigger catch-ups after downtime. Don't make a manual run require opening the Apps Script editor.

**Backfill mode** — first run on a new property should look back `lookback_days` (from config) to populate the campaign log without generating annotations for historical campaigns. A boolean flag in config (`backfill_complete`) that the script sets after the first run handles this cleanly.

---

### Phase 6 — Add-on packaging (3–5 days, separate effort)

This only makes sense after Phase 1–5 are solid and tested on at least 2–3 real properties. The add-on layer is UI chrome — it shouldn't change the core logic.

The add-on adds a sidebar with:
- Property ID input + "Validate" button (calls the Data API to confirm access)
- Threshold sliders (min sessions, reactivation days)
- "Install trigger" button (sets up the daily schedule)
- Last run status pulled from the run log tab

**The meaningful constraint**: Workspace Add-ons run under the installing user's OAuth credentials. If that person leaves the organisation or loses GA4 access, the trigger breaks. Worth documenting this clearly. For agency use, install under a shared/service Google account.

Publishing to the Marketplace requires a privacy policy, OAuth verification (takes 1–2 weeks from Google), and a GCP project in good standing. For internal agency use, sharing as an unlisted add-on via direct link sidesteps all of that.

---
