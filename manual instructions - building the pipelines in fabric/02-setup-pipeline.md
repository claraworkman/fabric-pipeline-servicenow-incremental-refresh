# Step 2: Build the Pipeline in Fabric Data Factory

This guide walks through creating each pipeline activity, configuring connections, and wiring up the dependency chain.

---

## 2.1 Create the Pipeline

1. In your Fabric workspace, click **+ New item** → **Data pipeline**
2. Name it: `ServiceNow-Ingestion`
3. You'll land on the pipeline canvas (empty)

---

## 2.2 Add the Pipeline Parameter

The pipeline needs a parameter to define which ServiceNow tables to ingest.

1. Click on the **pipeline canvas background** (not on any activity)
2. In the bottom panel, click **Parameters**
3. Click **+ New**
4. Configure:
   - **Name:** `tables`
   - **Type:** Array
   - **Default value:**

```json
[{"tableName": "incident"}]
```

Start with one table. After testing, expand to:

```json
[
  {"tableName": "incident"},
  {"tableName": "change_request"},
  {"tableName": "cmdb_ci_server"},
  {"tableName": "sc_request"}
]
```

---

## 2.3 Add the ForEach Activity

1. From the **Activities** panel, drag a **ForEach** onto the canvas
2. Name it: `Looping Through Tables`
3. In the **Settings** tab:
   - **Sequential:** Uncheck (enables parallel execution)
   - **Batch count:** Leave default (20) or set to match your table count
   - **Items:** Click in the field → **Add dynamic content** → enter:

```
@pipeline().parameters.tables
```

4. Click inside the ForEach (the pencil icon or double-click) to enter the inner canvas

---

## 2.4 Activity 1: Lookup — GetWatermark

Inside the ForEach, add the first activity:

1. Drag a **Lookup** activity onto the ForEach canvas
2. Name it: `GetWatermark`

### Settings tab

| Setting | Value |
|---|---|
| **Data store type** | External |
| **Connection type** | SQL Database |
| **Connection** | Select `watermark-servicenow` (your Fabric SQL Database) |
| **Use query** | Query |
| **First row only** | ✅ Checked |

### Query (Add dynamic content)

Click in the Query box → **Add dynamic content** → paste:

```
SELECT ISNULL(
    CONVERT(VARCHAR(19), watermark_value, 120),
    '1970-01-01 00:00:00'
) AS watermark
FROM dbo.watermark_tracking
WHERE table_name = '@{item().tableName}'
```

### What this does

- Reads the stored watermark timestamp for the current table
- `CONVERT(..., 120)` formats it as `yyyy-MM-dd HH:mm:ss` (ServiceNow-compatible)
- `ISNULL` defaults to `1970-01-01` if no row exists (full load on first run)
- Returns a single column `watermark` with the timestamp string

---

## 2.5 Activity 2: Copy Activity — Copy ServiceNow Data

After the Lookup, add the Copy Activity:

1. Drag a **Copy data** activity onto the ForEach canvas
2. Name it: `Copy ServiceNow Data`
3. **Draw a dependency arrow** from `GetWatermark` → `Copy ServiceNow Data`

### Configure the dependency

This is critical — click the dependency arrow and set:

- ✅ **Succeeded**
- ✅ **Failed**

Both must be checked. This ensures the Copy Activity runs even on first execution when the Lookup may fail (no watermark row yet).

### Source tab

| Setting | Value |
|---|---|
| **Data store type** | External |
| **Connection type** | ServiceNow |
| **Connection** | Select or create your ServiceNow connection |
| **Table** | Click → **Add dynamic content** → `@item().tableName` |

#### ServiceNow Connection Setup (if creating new)

| Field | Value |
|---|---|
| **Connection name** | `ServiceNow-Connection` |
| **Server URL** | `https://<your-instance>.service-now.com` |
| **Authentication kind** | Basic |
| **Username** | Your ServiceNow service account |
| **Password** | Service account password |

### Source filter (Query Builder)

Under the **Source** tab, expand **Advanced** and find the **Query Builder** / filter expression section:

1. Click **Add dynamic content** for the filter
2. Add a filter row:
   - **Column:** `sys_updated_on`
   - **Operator:** `>=` (greater than or equal to)
   - **Value:** Click → **Add dynamic content** → paste:

```
@activity('GetWatermark').output.firstRow.watermark
```

> **Alternative (handles Lookup failure):** If you want to handle the case where the Lookup fails (no watermark row), use this expression instead:
> ```
> @if(equals(activity('GetWatermark').status, 'Succeeded'), activity('GetWatermark').output.firstRow.watermark, '1970-01-01 00:00:00')
> ```

### Destination tab

| Setting | Value |
|---|---|
| **Data store type** | Workspace |
| **Workspace data store type** | Lakehouse |
| **Lakehouse** | Select `servicenow_data` |
| **Root folder** | Tables |
| **Table name** | Click → **Add dynamic content** → `@item().tableName` |
| **Table action** | **Upsert** |
| **Key columns** | Click **+ Add** → select `sys_id` |

### What this does

- Pulls rows from ServiceNow where `sys_updated_on >= watermark`
- Writes to the Lakehouse table with Upsert (MERGE on `sys_id`)
- New rows are inserted, existing rows (same `sys_id`) are updated
- If the table doesn't exist in the Lakehouse, it's created automatically

---

## 2.6 Activity 3: Stored Procedure — UpdateWatermark

After the Copy Activity, add the final activity:

1. Drag a **Stored procedure** activity onto the ForEach canvas
2. Name it: `Update Watermark`
3. **Draw a dependency arrow** from `Copy ServiceNow Data` → `Update Watermark`

### Configure the dependency

Click the dependency arrow and set:

- ✅ **Succeeded** only
- ❌ **Failed** — do NOT check

The watermark should only advance after a successful copy.

### Settings tab

| Setting | Value |
|---|---|
| **Data store type** | External |
| **Connection type** | SQL Database |
| **Connection** | Select `watermark-servicenow` |
| **Stored procedure name** | `dbo.usp_UpdateWatermark` |

### Stored procedure parameters

Click **Import parameters** or add them manually:

| Parameter | Type | Value |
|---|---|---|
| `tableName` | String | `@{item().tableName}` (Add dynamic content) |
| `watermarkValue` | String | `@{utcNow('yyyy-MM-dd HH:mm:ss')}` (Add dynamic content) |

> **Important:** Use **String** type for `watermarkValue`, not DateTime. The `utcNow()` function returns a string, and the stored procedure handles the implicit conversion to DATETIME2. Using DateTime type can cause a `SqlDateTime overflow` error.

---

## 2.7 Final Pipeline Layout

Your ForEach canvas should look like this:

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ForEach: Looping Through Tables                                         │
│                                                                          │
│  ┌─────────────┐  Succeeded  ┌───────────────────┐  Succeeded  ┌──────┐ │
│  │ GetWatermark │──+Failed──►│ Copy ServiceNow    │───only────►│Update│ │
│  │  (Lookup)    │            │ Data (Copy)        │            │Water-│ │
│  └─────────────┘            └───────────────────┘            │mark  │ │
│                                                               │(SP)  │ │
│                                                               └──────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2.8 Add a Schedule Trigger (Optional)

To run the pipeline automatically:

1. Click **Schedule** in the pipeline toolbar
2. Configure:
   - **Recurrence:** Hourly, Daily, etc.
   - **Start time:** When you want it to begin
   - **Time zone:** Your preferred time zone
3. Click **Apply**

### Recommended frequencies

| Use Case | Frequency |
|---|---|
| Real-time ops dashboard | Every 15-30 minutes |
| Daily reporting | Once daily (e.g., 6:00 AM) |
| Weekly analytics | Once weekly |
| Development/testing | Manual trigger only |

---

## Pipeline Parameter Reference

### Single table (testing)

```json
[{"tableName": "incident"}]
```

### Multiple tables (production)

```json
[
  {"tableName": "incident"},
  {"tableName": "change_request"},
  {"tableName": "sc_request"},
  {"tableName": "sc_req_item"},
  {"tableName": "cmdb_ci_server"},
  {"tableName": "sys_user"},
  {"tableName": "sys_user_group"},
  {"tableName": "problem"},
  {"tableName": "task"},
  {"tableName": "kb_knowledge"}
]
```

---

## Next Step

→ [03-testing-and-validation.md](03-testing-and-validation.md) — Test and validate the pipeline
