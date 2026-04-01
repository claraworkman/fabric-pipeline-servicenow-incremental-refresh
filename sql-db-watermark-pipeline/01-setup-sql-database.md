# Step 1: Set Up the Fabric SQL Database

This guide walks through creating a Fabric SQL Database to store watermark values for incremental ServiceNow ingestion.

---

## 1.1 Create the SQL Database in Fabric

1. Open your **Fabric workspace** (e.g., `ServiceNow-Ingestion-Pipeline`)
2. Click **+ New item**
3. Select **SQL Database** (under the "Store data" section)
4. Name it: `watermark-servicenow`
5. Click **Create**

> **Note:** The SQL Database uses a different billing model than Lakehouse — it consumes SQL compute CUs, not Spark CUs. For a small watermark table with occasional reads/writes, the cost is negligible.

---

## 1.2 Create the Watermark Tracking Table

Open the SQL Database query editor (click the database name → **New Query**) and run:

```sql
CREATE TABLE dbo.watermark_tracking (
    table_name      NVARCHAR(128)   NOT NULL PRIMARY KEY,
    watermark_value DATETIME2       NOT NULL DEFAULT '1970-01-01 00:00:00'
);
```

### What each column does

| Column | Type | Purpose |
|---|---|---|
| `table_name` | NVARCHAR(128) | ServiceNow table name (e.g., `incident`, `change_request`) |
| `watermark_value` | DATETIME2 | Last successful pipeline run timestamp for this table |

The `1970-01-01` default means the first pipeline run for any table pulls all historical records.

---

## 1.3 Seed Watermark Rows

Insert a row for each ServiceNow table you plan to ingest:

```sql
-- Start with one table for testing
INSERT INTO dbo.watermark_tracking (table_name, watermark_value)
VALUES ('incident', '1970-01-01 00:00:00');
```

After validating with `incident`, add more tables:

```sql
INSERT INTO dbo.watermark_tracking (table_name, watermark_value)
VALUES 
    ('change_request',  '1970-01-01 00:00:00'),
    ('cmdb_ci_server',  '1970-01-01 00:00:00'),
    ('sc_request',      '1970-01-01 00:00:00'),
    ('sys_user',        '1970-01-01 00:00:00'),
    ('sys_user_group',  '1970-01-01 00:00:00'),
    ('problem',         '1970-01-01 00:00:00'),
    ('task',            '1970-01-01 00:00:00');
```

---

## 1.4 Create the Update Watermark Stored Procedure

This stored procedure is called by the pipeline after each successful Copy Activity. It uses a MERGE to handle both first-run inserts and subsequent updates:

```sql
CREATE PROCEDURE dbo.usp_UpdateWatermark
    @tableName      NVARCHAR(128),
    @watermarkValue NVARCHAR(50)
AS
BEGIN
    MERGE dbo.watermark_tracking AS target
    USING (
        SELECT @tableName AS table_name, 
               CAST(@watermarkValue AS DATETIME2) AS watermark_value
    ) AS source
    ON target.table_name = source.table_name
    WHEN MATCHED THEN 
        UPDATE SET watermark_value = source.watermark_value
    WHEN NOT MATCHED THEN 
        INSERT (table_name, watermark_value) 
        VALUES (source.table_name, source.watermark_value);
END;
GO
```

### Why MERGE (not just UPDATE)?

If you forget to seed a watermark row for a new table, the MERGE will insert it automatically on the first successful pipeline run. This makes the pipeline self-healing.

---

## 1.5 Verify the Setup

Run these queries to confirm everything is in place:

```sql
-- Check the watermark table
SELECT * FROM dbo.watermark_tracking;
```

Expected output:
| table_name | watermark_value |
|---|---|
| incident | 1970-01-01 00:00:00.0000000 |

```sql
-- Test the stored procedure
EXEC dbo.usp_UpdateWatermark @tableName = 'incident', @watermarkValue = '2026-01-01 12:00:00';
SELECT * FROM dbo.watermark_tracking WHERE table_name = 'incident';
```

Expected: watermark_value = `2026-01-01 12:00:00.0000000`

```sql
-- Reset it back for testing
UPDATE dbo.watermark_tracking SET watermark_value = '1970-01-01 00:00:00' WHERE table_name = 'incident';
```

---

## 1.6 Lookup Query (Used by Pipeline)

The pipeline's Lookup activity runs this query to read the watermark. You don't need to run this manually — it's here for reference:

```sql
SELECT ISNULL(
    CONVERT(VARCHAR(19), watermark_value, 120),
    '1970-01-01 00:00:00'
) AS watermark
FROM dbo.watermark_tracking
WHERE table_name = '@{item().tableName}'
```

### Why CONVERT with style 120?

ServiceNow expects timestamps in `yyyy-MM-dd HH:mm:ss` format. `CONVERT(VARCHAR(19), ..., 120)` produces exactly that format. Without it, DATETIME2 may serialize with extra precision (`.0000000`) that the ServiceNow filter doesn't handle well.

---

## Next Step

→ [02-setup-pipeline.md](02-setup-pipeline.md) — Build the pipeline activities
