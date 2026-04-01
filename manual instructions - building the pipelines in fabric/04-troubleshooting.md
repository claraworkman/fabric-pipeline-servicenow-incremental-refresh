# Step 4: Troubleshooting

Common errors encountered when building this pipeline, with root causes and fixes. All of these were discovered and resolved during development.

---

## Error: SqlDateTime overflow

**Symptom:** The Stored Procedure activity fails with:
```
SqlDateTime overflow. Must be between 1/1/1753 12:00:00 AM and 12/31/9999 11:59:59 PM.
```

**Root cause:** The `watermarkValue` parameter type is set to **DateTime** in the Stored Procedure activity. The `utcNow()` function returns a string, and Fabric tries to convert it to a SQL DateTime, which overflows.

**Fix:** Change the parameter type from **DateTime** to **String**:

| Parameter | Type | Value |
|---|---|---|
| `watermarkValue` | **String** (not DateTime) | `@{utcNow('yyyy-MM-dd HH:mm:ss')}` |

The stored procedure's DATETIME2 column handles the implicit conversion from string correctly.

---

## Error: Tab character in table_name

**Symptom:** The watermark table has a row where `table_name` starts with a tab character (e.g., `\tincident`), causing the Lookup to return no rows for `incident`.

**Root cause:** When typing the stored procedure parameter value in the Fabric UI, a tab character was accidentally included.

**Fix:**

1. Check the watermark table:
```sql
SELECT table_name, LEN(table_name) AS name_length 
FROM dbo.watermark_tracking;
```

If `incident` shows a length of 9 instead of 8, there's a hidden character.

2. Clean it up:
```sql
DELETE FROM dbo.watermark_tracking WHERE table_name LIKE '%incident%';
INSERT INTO dbo.watermark_tracking (table_name, watermark_value) VALUES ('incident', '1970-01-01 00:00:00');
```

3. Verify the stored procedure parameter uses **Add dynamic content** (not typed directly):
```
@{item().tableName}
```

---

## Error: Duplicate watermark rows

**Symptom:** The `watermark_tracking` table has multiple rows for the same table name, and the Lookup returns unexpected results.

**Root cause:** The stored procedure was using INSERT instead of MERGE, or the MERGE was matching on the wrong column.

**Fix:**

1. Clean up duplicates:
```sql
-- See all rows
SELECT * FROM dbo.watermark_tracking;

-- Remove duplicates (keep the latest)
;WITH cte AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY table_name ORDER BY watermark_value DESC) AS rn
    FROM dbo.watermark_tracking
)
DELETE FROM cte WHERE rn > 1;
```

2. Verify the stored procedure matches on `table_name`:
```sql
ALTER PROCEDURE dbo.usp_UpdateWatermark
    @tableName NVARCHAR(128),
    @watermarkValue NVARCHAR(50)
AS
BEGIN
    MERGE dbo.watermark_tracking AS target
    USING (SELECT @tableName AS table_name, CAST(@watermarkValue AS DATETIME2) AS watermark_value) AS source
    ON target.table_name = source.table_name
    WHEN MATCHED THEN UPDATE SET watermark_value = source.watermark_value
    WHEN NOT MATCHED THEN INSERT (table_name, watermark_value) VALUES (source.table_name, source.watermark_value);
END;
GO
```

---

## Error: Copy Activity reads all rows every time

**Symptom:** The Copy Activity does a full load on every run instead of incremental (rows read never goes to 0).

**Root cause:** The source filter expression (Query Builder) was removed or isn't configured correctly.

**Fix:** Verify the source filter is set:

1. Open the Copy Activity → **Source** tab
2. Check the Query Builder / filter section
3. The filter should be:
   - **Column:** `sys_updated_on`
   - **Operator:** `>=`
   - **Value:** `@activity('GetWatermark').output.firstRow.watermark`

If using the full expression with failure handling:
```
@if(equals(activity('GetWatermark').status, 'Succeeded'), activity('GetWatermark').output.firstRow.watermark, '1970-01-01 00:00:00')
```

---

## Error: Lakehouse Lookup T-SQL Query greyed out

**Symptom:** When configuring a Lookup activity with a Lakehouse connection, the "Query" radio button under "Use query" is greyed out. Only "Table" mode is available.

**Root cause:** This is a Fabric platform limitation. Lakehouse Lookup activities only support Table mode. T-SQL query mode requires a SQL Database or SQL analytics endpoint connection.

**Fix:** Use a **Fabric SQL Database** for the watermark table instead of a Lakehouse table. This is the approach used in this pipeline.

---

## Error: ForEach only processes one table

**Symptom:** The ForEach only shows 1 iteration even though you added multiple tables.

**Root cause:** The `tables` parameter still has only one entry.

**Fix:** Update the pipeline parameter:

1. Click the pipeline canvas background
2. Go to **Parameters** tab
3. Edit the `tables` parameter default value:

```json
[
  {"tableName": "incident"},
  {"tableName": "change_request"},
  {"tableName": "cmdb_ci_server"}
]
```

4. Save and re-run

---

## Error: Copy Activity succeeds but 0 rows written (first run)

**Symptom:** First run reads rows but writes 0 to the Lakehouse.

**Root cause:** The destination table action is set to "Append" or "Overwrite" instead of "Upsert", and the table doesn't exist yet.

**Fix:** Set the destination:
- **Table action:** Upsert
- **Key columns:** sys_id

Upsert creates the table on first run and handles both inserts and updates.

---

## Error: ServiceNow connection fails

**Symptom:** Copy Activity fails with authentication or connection errors to ServiceNow.

**Common causes and fixes:**

| Issue | Fix |
|---|---|
| Wrong URL format | Use `https://<instance>.service-now.com` (no trailing slash, no `/api/now/table/`) |
| Wrong auth type | Use **Basic** authentication (not OAuth2) for dev instances |
| Account locked | Check the ServiceNow instance for account lockout |
| IP restriction | Add Fabric's IP ranges to ServiceNow's IP allowlist |
| Instance hibernated | Dev instances hibernate after inactivity — wake it up first |

---

## Error: Pipeline stuck "In progress" for a long time

**Symptom:** One or more activities show "In progress" or "Queued" for extended periods.

**Common causes:**

| Cause | Fix |
|---|---|
| ServiceNow rate limiting | Reduce parallel batch count or switch to sequential |
| Large initial load | First run pulling millions of rows — this is expected |
| Fabric capacity throttling | Check Monitor hub for capacity utilization |

---

## Useful Diagnostic Queries

### Check all watermarks

```sql
SELECT table_name, 
       CONVERT(VARCHAR(19), watermark_value, 120) AS last_loaded,
       DATEDIFF(MINUTE, watermark_value, GETUTCDATE()) AS minutes_ago
FROM dbo.watermark_tracking
ORDER BY watermark_value DESC;
```

### Reset a single table watermark (re-run full load)

```sql
UPDATE dbo.watermark_tracking 
SET watermark_value = '1970-01-01 00:00:00' 
WHERE table_name = 'incident';
```

### Reset all watermarks

```sql
UPDATE dbo.watermark_tracking SET watermark_value = '1970-01-01 00:00:00';
```

### Check for hidden characters in table names

```sql
SELECT table_name, 
       LEN(table_name) AS len,
       UNICODE(LEFT(table_name, 1)) AS first_char_unicode
FROM dbo.watermark_tracking;
```

---

## Back to Start

← [README.md](README.md) — Architecture overview and quick start
