# ServiceNow → Microsoft Fabric Incremental Ingestion Pipeline

Incremental ingestion from ServiceNow into a Fabric Lakehouse using the **Microsoft-recommended SQL Database watermark pattern**. A Fabric SQL Database tracks the last-loaded timestamp per table, and a ForEach loop drives Lookup → Copy (Upsert) → Stored Procedure for each ServiceNow table.

**No notebooks. No staging tables. No Spark compute. Three native pipeline activities per table.**

---

## Architecture

```mermaid
flowchart TB
    subgraph Workspace["Fabric Workspace"]
        direction TB
        
        subgraph Pipeline["Data Pipeline: ServiceNow-Ingestion"]
            Param["Parameter: tables<br/>[incident, change_request, ...]"]
            
            subgraph ForEach["ForEach: Looping Through Tables"]
                direction LR
                
                Lookup["🔍 Lookup<br/>GetWatermark<br/>──────────<br/>SQL Database<br/>SELECT watermark<br/>FROM watermark_tracking<br/>WHERE table_name = ..."]
                
                Copy["📦 Copy Activity<br/>CopyServiceNowData<br/>──────────<br/>Source: ServiceNow V2<br/>Filter: sys_updated_on &gt; watermark<br/>Sink: Lakehouse Upsert<br/>Key: sys_id"]
                
                SP["✏️ Stored Procedure<br/>UpdateWatermark<br/>──────────<br/>SQL Database<br/>usp_UpdateWatermark<br/>tableName + utcNow()"]
                
                Lookup -->|"Succeeded+Failed"| Copy
                Copy -->|"Succeeded only"| SP
            end
            
            Param --> ForEach
        end
        
        SQLDB[("SQL Database<br/>watermark-servicenow")]
        LH[("Lakehouse<br/>servicenow_data")]
    end
    
    SN["☁️ ServiceNow<br/>REST API"]
    
    SQLDB -.->|"read watermark"| Lookup
    SP -.->|"write watermark"| SQLDB
    SN -.->|"filtered rows"| Copy
    Copy -.->|"upsert on sys_id"| LH

    style Workspace fill:#f0f4ff,stroke:#4472c4,stroke-width:2px
    style Pipeline fill:#e8f5e9,stroke:#43a047,stroke-width:1px
    style ForEach fill:#fff8e1,stroke:#f9a825,stroke-width:1px
    style SQLDB fill:#e3f2fd,stroke:#1976d2
    style LH fill:#fce4ec,stroke:#c62828
    style SN fill:#f3e5f5,stroke:#7b1fa2
```

### Pipeline Flow (per table, inside ForEach)

![Pipeline Flow - ForEach with GetWatermark → Copy ServiceNow Data → Update Watermark](images/pipeline.png)

- **Succeeded + Failed** on the Lookup ensures first runs work even if no watermark row exists yet
- **Succeeded only** on the Stored Procedure ensures the watermark only advances after data is safely written

---

## Prerequisites

| Requirement | Details |
|---|---|
| **Fabric workspace** | With F2 or higher capacity attached |
| **Fabric Lakehouse** | Will be created during setup (e.g., `servicenow_data`) |
| **Fabric SQL Database** | Will be created during setup (e.g., `watermark-servicenow`) |
| **ServiceNow instance** | Developer or production instance with REST API access |
| **ServiceNow auth** | Service account with Basic authentication |
| **Workspace role** | Contributor or higher |

---

## Repo Contents

### Fabric Items (imported via Git Integration)

| Folder | Type | Description |
|---|---|---|
| `ServiceNow-Ingestion-SQL-Watermark.DataPipeline/` | Data Pipeline | The main incremental ingestion pipeline |
| `watermark-servicenow.SQLDatabase/` | SQL Database | Watermark tracking table and stored procedure |
| `servicenow_data.Lakehouse/` | Lakehouse | Destination for ServiceNow data |

### Documentation

| File | Description |
|---|---|
| `manual instructions - building the pipelines in fabric/01-setup-sql-database.md` | Create the SQL Database, watermark table, and stored procedure |
| `manual instructions - building the pipelines in fabric/02-setup-pipeline.md` | Step-by-step pipeline activity configuration |
| `manual instructions - building the pipelines in fabric/03-testing-and-validation.md` | Testing methodology: single-table → multi-table |
| `manual instructions - building the pipelines in fabric/04-troubleshooting.md` | Common errors and fixes |

---

## Deployment Option 1: Fabric Git Integration (Recommended)

Import the pipeline directly into a Fabric workspace via Git Integration.

> **At a glance — 6 steps:**
> 1. Create a Fabric workspace
> 2. Connect the workspace to this GitHub repo (`fabric-export` branch)
> 3. Run the SQL scripts to set up the watermark schema
> 4. Create a ServiceNow connection
> 5. Point each pipeline activity to your workspace items
> 6. Test the pipeline

### Step 1: Create a Fabric workspace

1. Go to [app.fabric.microsoft.com](https://app.fabric.microsoft.com) → **Workspaces** → **+ New workspace**
2. Name it (e.g., `ServiceNow-Ingestion`)
3. Assign a Fabric capacity (F64 or higher)

### Step 2: Connect to this GitHub repo

1. Open the workspace → **Workspace settings** → **Git integration**
2. Configure:
   - **Provider:** GitHub
   - **Account:** Create or select a GitHub connection (PAT needs `repo` scope)
   - **Repository:** `fabric-pipeline-servicenow-incremental-refresh`
   - **Branch:** `fabric-export` (this branch contains the Fabric-exported item formats required by Git Integration)
   - **Git folder:** `/`
3. Click **Connect and sync**
4. When prompted, choose **"Update workspace from Git"** to import all items

> **Why `fabric-export` and not `main`?** Fabric Git Integration requires items in Fabric's internal export format (`.platform` files + specific JSON structures). The `fabric-export` branch contains these Fabric-exported items. The `main` branch includes additional documentation and the same Fabric items.

### Step 3: Set up the SQL Database

Git Integration imports the SQL Database project, but the watermark table and stored procedure may not deploy automatically. You'll verify they exist and create them if needed.

1. Open `watermark-servicenow` in the Fabric portal
2. Expand **Tables** in the left panel — if `dbo.watermark_tracking` already exists, skip to sub-step 4 (seed data). Otherwise, click **New Query** and run:

```sql
CREATE TABLE dbo.watermark_tracking (
    table_name      NVARCHAR(128)   NOT NULL PRIMARY KEY,
    watermark_value DATETIME2       NOT NULL DEFAULT '1970-01-01 00:00:00'
);
```

3. Check if the stored procedure exists by expanding **Programmability → Stored Procedures** in the left panel. If `dbo.usp_UpdateWatermark` is missing, create it:

```sql
CREATE PROCEDURE dbo.usp_UpdateWatermark
    @tableName      NVARCHAR(100),
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

4. Seed the watermark row for initial testing:

```sql
INSERT INTO dbo.watermark_tracking (table_name, watermark_value)
VALUES ('incident', '1970-01-01 00:00:00');
```

### Step 4: Create the ServiceNow connection

1. Open the imported pipeline `ServiceNow-Ingestion-SQL-Watermark`
2. Click the **Copy Activity** (`CopyServiceNowData`) → go to the **Source** tab
3. You'll see a broken connection indicator — **this is expected** (connections are workspace-specific and not stored in Git)
4. Click the connection dropdown → **+ New connection**
5. Configure:

| Field | Value |
|---|---|
| **Connection name** | `ServiceNow-Connection` |
| **Server URL** | `https://<your-instance>.service-now.com` |
| **Authentication** | Basic |
| **Username** | Your ServiceNow service account |
| **Password** | Service account password |

### Step 5: Update connection references

Each activity needs to point to your workspace items. Click on each activity inside the ForEach, then update the connection on the appropriate tab:

| Activity | Tab | What to select |
|---|---|---|
| **GetWatermark** (Lookup) | Settings → Connection | Your `watermark-servicenow` SQL Database |
| **CopyServiceNowData** (Copy) | Source → Connection | Your ServiceNow connection (created in Step 4) |
| **CopyServiceNowData** (Copy) | Destination → Connection | Your `servicenow_data` Lakehouse |
| **UpdateWatermark** (Stored Procedure) | Settings → Connection | Your `watermark-servicenow` SQL Database |

> **Tip:** Click the ForEach activity, then click the **pencil icon** (✏️) to open it and access the inner activities.

### Step 6: Test

1. Run the pipeline with the default parameter: `[{"tableName": "incident"}]`
2. First run → full load (all incident rows copied)
3. Second run → **0 rows read** (proves incremental works)
4. Update an incident in ServiceNow → third run picks up **1 changed row**

---

## Deployment Option 2: Manual Setup

If you prefer to build the pipeline from scratch instead of importing from Git, follow the step-by-step guides:

1. [01-setup-sql-database.md](manual%20instructions%20-%20building%20the%20pipelines%20in%20fabric/01-setup-sql-database.md) — Create SQL Database, watermark table, stored procedure
2. [02-setup-pipeline.md](manual%20instructions%20-%20building%20the%20pipelines%20in%20fabric/02-setup-pipeline.md) — Build the pipeline activities from scratch
3. [03-testing-and-validation.md](manual%20instructions%20-%20building%20the%20pipelines%20in%20fabric/03-testing-and-validation.md) — Test single-table, then scale to many
4. [04-troubleshooting.md](manual%20instructions%20-%20building%20the%20pipelines%20in%20fabric/04-troubleshooting.md) — Common errors and fixes

---

## Scaling to Multiple Tables

After validating with `incident`, add more ServiceNow tables:

### 1. Add watermark rows

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

### 2. Update the pipeline parameter

Edit the `tables` parameter default value:

```json
[
  {"tableName": "incident"},
  {"tableName": "change_request"},
  {"tableName": "cmdb_ci_server"},
  {"tableName": "sc_request"}
]
```

### 3. Run

The ForEach executes all tables in parallel by default. Each table runs the full Lookup → Copy → Stored Procedure chain independently.

---

## Key Design Decisions

### Why SQL Database for watermarks (not Lakehouse)?

Fabric Lakehouse Lookup activities only support **Table mode** — the T-SQL Query option is greyed out. You cannot run parameterized SQL queries against a Lakehouse from a Lookup activity. A Fabric SQL Database supports full T-SQL query mode, making it the correct choice for watermark tracking.

### Why Upsert (not Append)?

ServiceNow records can be updated. Using Append would create duplicate rows. Upsert performs a MERGE on `sys_id`, so:
- New records are inserted
- Modified records are updated in-place
- No duplicates

### Why Succeeded + Failed on the Lookup dependency?

On the first run for any table, there may be no watermark row yet. The Lookup would fail. By allowing the Copy Activity to run on both Succeeded and Failed, the pipeline handles first runs gracefully (defaulting to `1970-01-01` for a full load).

### Why String type for watermarkValue (not DateTime)?

The `utcNow()` function returns a string. Fabric's Stored Procedure activity can cause a `SqlDateTime overflow` error when using DateTime type. String type avoids this — the stored procedure's CAST to DATETIME2 handles conversion correctly.

---

## Scheduling

Add a schedule trigger in the pipeline toolbar:

| Use Case | Recommended Frequency |
|---|---|
| Real-time ops dashboard | Every 15–30 minutes |
| Daily reporting | Once daily (e.g., 6:00 AM) |
| Weekly analytics | Once weekly |
| Development/testing | Manual trigger only |

---

## Troubleshooting Quick Reference

| Error | Fix |
|---|---|
| `SqlDateTime overflow` | Change `watermarkValue` parameter type to **String** |
| Copy reads all rows every run | Verify source filter: `sys_updated_on >= @activity('GetWatermark').output.firstRow.watermark` |
| Duplicate watermark rows | Use MERGE stored procedure (not INSERT) |
| Lakehouse Lookup query greyed out | Use SQL Database for watermarks instead |
| ServiceNow connection fails | Check URL format (`https://<instance>.service-now.com`), auth type (Basic), account not locked |
| Hidden tab character in table_name | Check with `LEN(table_name)` — delete and re-insert clean row |

See [04-troubleshooting.md](manual%20instructions%20-%20building%20the%20pipelines%20in%20fabric/04-troubleshooting.md) for detailed explanations of each error.

---

## Useful SQL Queries

```sql
-- Check all watermarks
SELECT table_name,
       CONVERT(VARCHAR(19), watermark_value, 120) AS last_loaded,
       DATEDIFF(MINUTE, watermark_value, GETUTCDATE()) AS minutes_ago
FROM dbo.watermark_tracking
ORDER BY watermark_value DESC;

-- Reset a single table (re-run full load)
UPDATE dbo.watermark_tracking
SET watermark_value = '1970-01-01 00:00:00'
WHERE table_name = 'incident';

-- Reset all watermarks
UPDATE dbo.watermark_tracking SET watermark_value = '1970-01-01 00:00:00';
```
Disclaimer: The attached diagrams and code are provided AS IS without warranty of any kind and should not be interpreted as an offer or commitment on the part of Microsoft, and Microsoft cannot guarantee the accuracy of any information presented. MICROSOFT MAKES NO WARRANTIES, EXPRESS OR IMPLIED, IN THIS DIAGRAM(s) CODE SAMPLE(s).

---

## License

This project is provided as-is for demonstration and deployment purposes.
