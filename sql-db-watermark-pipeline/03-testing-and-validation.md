# Step 3: Testing and Validation

How to confirm the pipeline works correctly — first with one table, then with many.

---

## 3.1 Test with a Single Table

### First run (full load)

1. Set the `tables` parameter to: `[{"tableName": "incident"}]`
2. Click **Save & run** → **Save & run** in the dialog
3. Watch the Output tab — you should see:

| Activity | Expected Result |
|---|---|
| GetWatermark | ✅ Succeeded — returns `1970-01-01 00:00:00` |
| Copy ServiceNow Data | ✅ Succeeded — reads **all** incident rows |
| Update Watermark | ✅ Succeeded — sets watermark to current UTC time |

4. Click on the Copy Activity output → check **Rows read** and **Rows written**
5. Open the Lakehouse → you should see a new `incident` table with all rows

### Second run (incremental proof)

1. Run the pipeline again **without changing anything** in ServiceNow
2. Expected results:

| Activity | Expected Result |
|---|---|
| GetWatermark | ✅ Returns the timestamp from the first run |
| Copy ServiceNow Data | ✅ Reads **0 rows** (no changes since last run) |
| Update Watermark | ✅ Advances watermark to current UTC |

**0 rows read on re-run = incremental loading is working correctly.**

### Third run (change detection)

1. Go to your ServiceNow instance
2. Open any incident and make a small change (e.g., update the description)
3. Run the pipeline again
4. Expected: **1 row read, 1 row written** (the modified incident)
5. Check the Lakehouse — the row should be updated (not duplicated)

---

## 3.2 Scale to Multiple Tables

Once the single-table test passes:

### Add watermark rows

In the SQL Database, run:

```sql
INSERT INTO dbo.watermark_tracking (table_name, watermark_value)
VALUES 
    ('change_request',  '1970-01-01 00:00:00'),
    ('cmdb_ci_server',  '1970-01-01 00:00:00');
```

### Update the pipeline parameter

Change the `tables` parameter to:

```json
[
  {"tableName": "incident"},
  {"tableName": "change_request"},
  {"tableName": "cmdb_ci_server"}
]
```

### Run and verify

1. Click **Save & run**
2. In the Output tab, you should see the ForEach expand with **3 iterations**
3. Each iteration runs GetWatermark → Copy → UpdateWatermark independently
4. New tables (`change_request`, `cmdb_ci_server`) will do a **full load** (first run)
5. `incident` will do an **incremental load** (watermark already set from previous test)

### Check the Lakehouse

You should now see 3 tables:
- `incident` (existing, updated incrementally)
- `change_request` (new, full load)
- `cmdb_ci_server` (new, full load)

### Re-run to confirm all three are incremental

Run the pipeline one more time. All three tables should show **0 rows read** — proving incremental works across all tables.

---

## 3.3 Verify Watermarks

Query the SQL Database to see watermark values:

```sql
SELECT table_name, 
       CONVERT(VARCHAR(19), watermark_value, 120) AS last_loaded
FROM dbo.watermark_tracking
ORDER BY table_name;
```

Expected output:

| table_name | last_loaded |
|---|---|
| change_request | 2026-03-31 20:45:00 |
| cmdb_ci_server | 2026-03-31 20:45:00 |
| incident | 2026-03-31 20:45:00 |

All timestamps should reflect the last successful pipeline run.

---

## 3.4 Parallel vs. Sequential Execution

By default, ForEach runs iterations **in parallel** (up to the batch count). This means all 3 tables load simultaneously.

### When to use sequential

If you're hitting ServiceNow API rate limits, switch to sequential:
1. Click on the ForEach activity
2. Go to **Settings**
3. Check **Sequential**

### When to use parallel (recommended)

For most scenarios, parallel is better — it reduces total pipeline duration:

| Tables | Sequential | Parallel |
|---|---|---|
| 3 tables | ~2.5 min (3 × 50s) | ~50s (longest table) |
| 10 tables | ~8 min | ~50s |

---

## 3.5 Handling Deletes

The watermark pattern captures **inserts and updates** but not **hard deletes** from ServiceNow.

### Option A: Weekly full reconciliation (recommended)

Create a separate pipeline that runs weekly:
1. Full-load all ServiceNow tables into staging tables
2. Compare staging vs. Lakehouse to identify deleted records
3. Soft-delete or remove orphaned rows

### Option B: ServiceNow audit log

Use ServiceNow's `sys_audit_delete` table to identify deleted records. This table tracks hard deletes with the deleted `sys_id` and timestamp.

### Option C: Accept eventual consistency

For most analytics and reporting use cases, missing a delete is acceptable. Deleted incidents don't typically affect operational dashboards.

---

## 3.6 Validation Checklist

| Check | How to Verify | ✅ |
|---|---|---|
| Full load works | First run reads all rows for each table | ☐ |
| Incremental works | Re-run reads 0 rows (no changes) | ☐ |
| Change detection works | Modify a record → pipeline picks up 1 row | ☐ |
| Upsert works | Modified row is updated, not duplicated | ☐ |
| Multi-table works | ForEach iterates over all tables in parameter | ☐ |
| Watermark updates | SQL DB timestamps advance after each run | ☐ |
| Failure handling | Watermark doesn't advance on Copy failure | ☐ |
| New table auto-creates | Table is created in Lakehouse on first load | ☐ |

---

## Next Step

→ [04-troubleshooting.md](04-troubleshooting.md) — Common errors and how to fix them
