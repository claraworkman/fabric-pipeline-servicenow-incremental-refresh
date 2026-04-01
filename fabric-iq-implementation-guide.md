# Fabric IQ Implementation Guide: ServiceNow Data to Copilot Studio

A step-by-step guide for building a **semantic model first**, then layering a **business graph ontology** in Microsoft Fabric IQ from ServiceNow data ingested into OneLake, and exposing it to Copilot Studio through a data agent.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Architecture Overview](#architecture-overview)
3. [Why Build a Semantic Model First](#why-build-a-semantic-model-first)
4. [Phase 1: Prepare Your Data in OneLake](#phase-1-prepare-your-data-in-onelake)
5. [Phase 2: Build the Semantic Model](#phase-2-build-the-semantic-model)
6. [Phase 3: Design the Ontology](#phase-3-design-the-ontology)
7. [Phase 4: Define Entities](#phase-4-define-entities)
8. [Phase 5: Define Relationships](#phase-5-define-relationships)
9. [Phase 6: Add Semantic Descriptions](#phase-6-add-semantic-descriptions)
10. [Phase 7: Build and Validate in Fabric IQ](#phase-7-build-and-validate-in-fabric-iq)
11. [Phase 8: Expose to Copilot Studio](#phase-8-expose-to-copilot-studio)
12. [Best Practices](#best-practices)
13. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- Microsoft Fabric workspace (F64 or higher capacity recommended)
- ServiceNow data already ingested into a Fabric Lakehouse or Warehouse
- Fabric IQ enabled on your tenant (admin setting)
- Copilot Studio license (for the data agent)
- Workspace contributor or higher role
- Power BI Desktop or Fabric web authoring (for semantic model creation)

---

## Architecture Overview

```
┌──────────────┐      ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  ServiceNow  │─────▶│  OneLake         │─────▶│  Semantic Model  │─────▶│  Fabric IQ       │
│  (source)    │ ETL  │  Lakehouse/WH    │      │  (DirectLake)    │      │  Ontology        │
└──────────────┘      │  (Gold tables)   │      │  DAX measures,   │      │  (Business Graph)│
                      └──────────────────┘      │  relationships   │      └────────┬─────────┘
                                                └───────┬──────────┘               │
                                                        │                          │
                                                        ▼                          ▼
                                                ┌──────────────────┐      ┌──────────────────┐
                                                │  Power BI        │      │  Copilot Studio  │
                                                │  Reports         │      │  Data Agent      │
                                                └──────────────────┘      └──────────────────┘
```

---

## Why Build a Semantic Model First

Building a Power BI semantic model before the ontology provides several advantages:

| Benefit | Details |
|---|---|
| **Single source of truth for business logic** | DAX measures (SLA breach rate, average resolution time, priority scoring) are defined once and reused by both Power BI reports and the ontology |
| **Validated data layer** | The semantic model lets you test relationships, data types, and business logic in Power BI before exposing them to AI |
| **Multiple consumers** | The same model serves Power BI dashboards, Excel, Copilot in Power BI, and Copilot Studio — no duplicate logic |
| **DirectLake performance** | Semantic models in DirectLake mode query the lakehouse directly with near-real-time performance |
| **Governance and endorsement** | Semantic models support certification, endorsement, row-level security (RLS), and object-level security (OLS) |
| **Iterative development** | You can build reports and validate data quality before investing in the ontology layer |

**The recommended approach:** Build and validate the semantic model → then layer the ontology on top for graph-shaped queries and Copilot Studio integration.

---

## Phase 1: Prepare Your Data in OneLake

Before building an ontology, ensure your ServiceNow data is clean, well-typed, and organized.

### 1.1 — Validate Ingested Tables

Confirm the following core ServiceNow tables (or their equivalents) exist in your Lakehouse:

| ServiceNow Table | Description |
|---|---|
| `incident` | IT service disruption records |
| `cmdb_ci` | Configuration items (servers, apps, services) |
| `sys_user` | User records |
| `sys_user_group` | Support groups and teams |
| `change_request` | Change management records |
| `task` | Generic task records |
| `cmdb_rel_ci` | CI-to-CI dependency relationships |
| `kb_knowledge` | Knowledge base articles |
| `problem` | Problem management records |
| `sc_request` | Service catalog requests |

### 1.2 — Build a Gold Layer

Create business-ready tables that the ontology will map to. Use Fabric notebooks or Dataflow Gen2:

**Dimension tables:**

| Gold Table | Source | Key Transformations |
|---|---|---|
| `dim_user` | `sys_user` | Cast dates, resolve manager sys_id to name, flag active/inactive |
| `dim_user_group` | `sys_user_group` | Flatten group hierarchy |
| `dim_ci` | `cmdb_ci` | Resolve CI class, operational status, environment |
| `dim_category` | `incident.category` | Deduplicate, create hierarchy (category → subcategory) |
| `dim_priority` | Derived | Static: P1-Critical, P2-High, P3-Medium, P4-Low |
| `dim_location` | `cmn_location` | Flatten to city/state/country |

**Fact tables:**

| Gold Table | Source | Key Transformations |
|---|---|---|
| `fact_incident` | `incident` | Cast timestamps, compute `resolution_hours`, flag `is_sla_breached` |
| `fact_change_request` | `change_request` | Cast timestamps, resolve approval status |
| `fact_problem` | `problem` | Link to root cause CI, compute age |
| `fact_request` | `sc_request` | Resolve catalog item, compute fulfillment time |

**Bridge tables:**

| Gold Table | Source | Purpose |
|---|---|---|
| `bridge_ci_relationship` | `cmdb_rel_ci` | Many-to-many CI dependency graph |
| `bridge_user_group_member` | `sys_user_grmember` | Many-to-many user-to-group membership |
| `bridge_incident_ci` | `task_ci` | Many-to-many incident-to-CI affected |

### 1.3 — Set Up Incremental Ingestion (Native ServiceNow Connector)

Fabric Data Factory has a **native ServiceNow V2 connector** that supports Copy Activity and Lookup Activity with Basic authentication. Use its **Query Builder** (equivalent to ServiceNow's condition builder) to implement a watermark-based incremental load with a staging + MERGE pattern.

#### Pipeline Architecture

```
ServiceNow
  ↓  ServiceNow V2 connector (query builder: sys_updated_on > watermark − 5 min)
staging_<table>  ← Copy Activity (overwrite each run)
  ↓  Notebook: dedup + Delta MERGE on sys_id
<table>  ← current-state table (your Gold layer for the semantic model)
  ↓
Semantic Model → Fabric IQ → Copilot Studio
```

**Per-table flow inside a ForEach activity:**

```
┌──────────────────────┐     ┌─────────────────────────────────┐     ┌──────────────────────┐
│ Lookup: GetWatermark │────▶│ Copy Activity                   │────▶│ Notebook: MERGE      │
│                      │     │ (ServiceNow V2 → staging table) │     │                      │
│ watermark − 5 min    │     │ query builder:                  │     │ dedup on sys_id       │
│ (overlap window)     │     │ sys_updated_on > @watermark     │     │ MERGE staging → main │
│                      │     │ sink: overwrite staging_<table>  │     │ update watermark     │
└──────────────────────┘     └─────────────────────────────────┘     │ (only on success)    │
                                                                     └──────────────────────┘
```

#### Best-Practice Safeguards

| Safeguard | Implementation |
|---|---|
| **Watermark on `sys_updated_on`** | Lookup reads last stored watermark → feeds into query builder filter |
| **Overlap window (5 min)** | Lookup subtracts 5 minutes from stored watermark before querying — catches late-arriving updates |
| **Dedup before MERGE** | Notebook deduplicates staging by `sys_id` (keeps latest `sys_updated_on`) — overlap window may pull duplicate rows |
| **MERGE on `sys_id`** | Delta MERGE upserts into the main table — inserts new, updates changed |
| **Watermark updated after success only** | Notebook sets watermark = `MAX(sys_updated_on)` from the batch, not `current_timestamp()` — prevents skipping records |
| **Run metadata in watermark table** | `run_id`, `rows_merged`, `last_run_timestamp` logged for auditability |
| **Delete detection** | Schedule a weekly full-load reconciliation pipeline (see caveat below) |

#### Step 1: Create the ServiceNow Connection

1. In your Fabric workspace, go to **Settings** → **Manage connections and gateways**.
2. Select **New connection** → **ServiceNow**.
3. Provide:
   - **Server URL:** `https://<instance>.service-now.com`
   - **Authentication:** Basic
   - **Username / Password:** ServiceNow service account credentials
4. Test and save.

#### Step 2: Configure the Copy Activity with Query Builder

In the pipeline's Copy Activity **Source** tab:

1. **Connection:** Select your ServiceNow connection.
2. **Table:** Select the ServiceNow table (e.g., `incident`).
3. **Query Builder** (under Advanced): Configure the filter expression for incremental loading.

The query builder uses the same syntax as ServiceNow's condition builder. For incremental loads, filter on `sys_updated_on > <watermark>`:

**Using the dynamic content expression parameter:**

```json
{
    "type": "Binary",
    "operators": [">"],
    "operands": [
        {
            "type": "Field",
            "value": "sys_updated_on"
        },
        {
            "type": "Constant",
            "value": "@{activity('GetWatermark').output.firstRow.watermark}"
        }
    ]
}
```

The Lookup activity applies the 5-minute overlap window before passing the watermark value. For a first run (no watermark yet), the Lookup returns `1970-01-01 00:00:00`, pulling all records.

#### Step 3: Configure the Sink (Lakehouse Staging Table)

In the **Destination** tab:
- **Data store:** Lakehouse
- **Lakehouse:** `ServiceNowLakehouse`
- **Table:** `staging_<tableName>` (e.g., `staging_incident`)
- **Table action:** **Overwrite** (staging is rebuilt each run — this is NOT your business table)

#### Step 4: MERGE Staging → Main Table

After the Copy Activity, a **Notebook Activity** deduplicates and MERGEs into the main table:

```python
table_name = notebookutils.pipeline.getParameterValue("table_name")
staging_df = spark.table(f"ServiceNowLakehouse.staging_{table_name}")

# Dedup: overlap window may pull the same sys_id twice
staging_df.createOrReplaceTempView("staging_raw")
spark.sql("""
    CREATE OR REPLACE TEMP VIEW staging_deduped AS
    SELECT * FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY sys_id ORDER BY sys_updated_on DESC
        ) as _rn FROM staging_raw
    ) WHERE _rn = 1
""")

columns = [c for c in staging_df.columns if not c.startswith("_")]
update_set = ", ".join([f"main.{c} = stg.{c}" for c in columns])
insert_cols = ", ".join(columns)
insert_vals = ", ".join([f"stg.{c}" for c in columns])

spark.sql(f"""
MERGE INTO ServiceNowLakehouse.{table_name} AS main
USING staging_deduped AS stg
ON main.sys_id = stg.sys_id
WHEN MATCHED THEN UPDATE SET {update_set}
WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
""")
```

#### Step 5: Watermark Tracking

The notebook updates `ingestion_watermark` **only after a successful MERGE**:

| Column | Type | Purpose |
|---|---|---|
| `table_name` | STRING | ServiceNow table name |
| `last_updated_on` | STRING | `MAX(sys_updated_on)` from the merged batch |
| `last_run_timestamp` | TIMESTAMP | When the pipeline ran |
| `last_run_id` | STRING | Pipeline `RunId` for traceability |
| `rows_merged` | INT | Number of records processed |

> **Key:** The watermark is set to `MAX(sys_updated_on)` from the batch data — not `GETDATE()` or `current_timestamp()`. This prevents skipping records that were updated in ServiceNow between the Copy start and completion.

#### Step 6: ForEach Loop for Multiple Tables

Wrap the Lookup → Copy → Notebook pattern in a **ForEach** activity with a pipeline parameter:

```json
"parameters": {
    "tables": {
        "type": "Array",
        "defaultValue": [
            { "tableName": "incident" },
            { "tableName": "cmdb_ci" },
            { "tableName": "sys_user" },
            { "tableName": "sys_user_group" },
            { "tableName": "change_request" },
            { "tableName": "cmdb_rel_ci" }
        ]
    }
}
```

- **Incremental key:** `sys_updated_on` (datetime) from ServiceNow
- **Refresh frequency:** Match your SLA requirements (hourly for P1 visibility, daily for reporting)
- **Schedule:** Add a pipeline trigger (Scheduled or Tumbling window)

#### Caveat: Handling Deletes

A `sys_updated_on` watermark captures inserts and updates but **does not detect hard deletes** in ServiceNow. Fabric's Copy Job CDC feature supports delete detection for some database sources (Azure SQL, Snowflake, etc.) but not ServiceNow.

**Recommended approach for delete detection:**
- Schedule a **weekly full-load reconciliation** pipeline that pulls the full table and identifies records present in Fabric but missing from ServiceNow
- Alternatively, use ServiceNow's audit log or business rules to track deletes if that's a hard requirement

For most ITSM analytics scenarios, incremental inserts/updates with periodic full reconciliation is sufficient.

> **Reference:** [Configure ServiceNow in a copy activity](https://learn.microsoft.com/en-us/fabric/data-factory/connector-servicenow-copy-activity) — full documentation for the native connector, Query Builder syntax, and expression parameter format.

---

## Phase 2: Build the Semantic Model

The semantic model is the governed business logic layer that sits between your Gold tables and downstream consumers (Power BI, ontology, Copilot).

### 2.1 — Create the Semantic Model

1. In your Fabric workspace, select **New** → **Semantic model**.
2. Name it `ServiceNow ITSM Model`.
3. Select **DirectLake** mode and point it to your Lakehouse containing the Gold tables.
4. Add the following tables:

| Semantic Model Table | Source Gold Table | Role |
|---|---|---|
| Incident | `fact_incident` | Fact |
| Change Request | `fact_change_request` | Fact |
| Problem | `fact_problem` | Fact |
| User | `dim_user` | Dimension |
| User Group | `dim_user_group` | Dimension |
| Configuration Item | `dim_ci` | Dimension |
| Priority | `dim_priority` | Dimension |
| Category | `dim_category` | Dimension |
| Location | `dim_location` | Dimension |
| Date | `dim_date` | Date table |
| CI Relationship | `bridge_ci_relationship` | Bridge |
| Group Membership | `bridge_user_group_member` | Bridge |

> **Important:** Create a `dim_date` table covering the full date range of your ServiceNow data (e.g., 2020-01-01 to 2030-12-31). Mark it as a **date table** in the semantic model (Table tools → Mark as date table) and relate it to each fact table's primary date column. This is required for DAX time intelligence functions like `DATESMTD`, `SAMEPERIODLASTYEAR`, etc.

### 2.2 — Define Relationships in the Model

Set up the star schema relationships in the semantic model:

```
Incident[assigned_to_id]        →  User[sys_id]             (Many-to-One)
Incident[assignment_group_id]   →  User Group[sys_id]       (Many-to-One)
Incident[cmdb_ci_id]            →  Configuration Item[sys_id](Many-to-One)
Incident[opened_by_id]          →  User[sys_id]             (Many-to-One, inactive)
Incident[priority]              →  Priority[value]          (Many-to-One)
Incident[category]              →  Category[name]           (Many-to-One)
Incident[opened_date]           →  Date[date]               (Many-to-One)
Change Request[assigned_to_id]  →  User[sys_id]             (Many-to-One)
Change Request[requested_by_id] →  User[sys_id]             (Many-to-One, inactive)
Change Request[cmdb_ci_id]      →  Configuration Item[sys_id](Many-to-One)
CI Relationship[parent_sys_id]  →  Configuration Item[sys_id](Many-to-One)
CI Relationship[child_sys_id]   →  Configuration Item[sys_id](Many-to-One, inactive)
Group Membership[user_sys_id]   →  User[sys_id]             (Many-to-One)
Group Membership[group_sys_id]  →  User Group[sys_id]       (Many-to-One)
```

> **Note:** Mark duplicate relationships to the same table as **inactive**. Use `USERELATIONSHIP()` in DAX measures when you need to activate them.

### 2.3 — Add DAX Measures

Create a `_Measures` table (or add to each fact table) with these core measures:

**Incident Measures:**

```dax
// Count of currently open incidents
Open Incidents = 
CALCULATE(
    COUNTROWS('Incident'),
    'Incident'[state] IN {"New", "In Progress", "On Hold"}
)

// Count of all incidents (any state)
Total Incidents = 
COUNTROWS('Incident')

// Average time to resolution in hours
Avg Resolution Hours = 
AVERAGEX(
    FILTER('Incident', NOT ISBLANK('Incident'[resolved_at])),
    'Incident'[resolution_hours]
)

// Percentage of incidents that breached SLA
SLA Breach Rate = 
DIVIDE(
    CALCULATE(COUNTROWS('Incident'), 'Incident'[is_sla_breached] = TRUE()),
    COUNTROWS('Incident'),
    0
)

// Open P1 (Critical) incidents
Open P1 Incidents = 
CALCULATE(
    COUNTROWS('Incident'),
    'Incident'[state] IN {"New", "In Progress", "On Hold"},
    'Incident'[priority] = 1
)

// Incidents opened in the current month (requires dim_date marked as date table)
Incidents This Month = 
CALCULATE(
    COUNTROWS('Incident'),
    DATESMTD('Date'[date])
)

// Median resolution time (more representative than average)
Median Resolution Hours = 
MEDIANX(
    FILTER('Incident', NOT ISBLANK('Incident'[resolved_at])),
    'Incident'[resolution_hours]
)
```

**Change Request Measures:**

```dax
// Open change requests
Open Changes = 
CALCULATE(
    COUNTROWS('Change Request'),
    'Change Request'[state] IN {"New", "Assess", "Authorize", "Scheduled", "Implement"}
)

// Emergency changes (high risk)
Emergency Changes = 
CALCULATE(
    COUNTROWS('Change Request'),
    'Change Request'[type] = "Emergency"
)

// Change success rate (closed without rollback)
Change Success Rate = 
DIVIDE(
    CALCULATE(
        COUNTROWS('Change Request'),
        'Change Request'[state] = "Closed",
        'Change Request'[close_code] = "Successful"
    ),
    CALCULATE(
        COUNTROWS('Change Request'),
        'Change Request'[state] = "Closed"
    ),
    0
)
```

### 2.4 — Add Descriptions to the Semantic Model

Add descriptions to every table and measure in the semantic model. These descriptions carry forward to the ontology and to Copilot:

| Object | Description |
|---|---|
| Incident (table) | Records of unplanned IT service disruptions. Also called tickets or cases. |
| User (table) | People in the organization — support engineers, managers, and end users. |
| Configuration Item (table) | IT assets tracked in the CMDB: servers, applications, databases, business services. |
| Open Incidents (measure) | Count of incidents in New, In Progress, or On Hold state. Excludes Resolved, Closed, and Canceled. |
| Avg Resolution Hours (measure) | Mean hours between incident creation and resolution. Excludes still-open incidents. |
| SLA Breach Rate (measure) | Fraction of incidents that exceeded their priority-based SLA target. 0 = no breaches, 1 = all breached. |

### 2.5 — Configure Row-Level Security (Optional)

If different teams should only see their own data:

```dax
// RLS role: "Assignment Group Filter"
// Applied to the User Group table
// Step 1: Resolve the current user's email to their sys_id via the User table
// Step 2: Find which groups that user belongs to via the bridge table
[sys_id] IN 
    SELECTCOLUMNS(
        FILTER(
            'Group Membership',
            'Group Membership'[user_sys_id] = 
                LOOKUPVALUE(
                    'User'[sys_id],
                    'User'[email], USERPRINCIPALNAME()
                )
        ),
        "group_id", 'Group Membership'[group_sys_id]
    )
```

> **Note:** This resolves `USERPRINCIPALNAME()` (which returns the user's email) to their `sys_id` via the User table, then looks up their group memberships. Map Azure AD security groups to RLS roles so that Network Operations only sees their incidents, SAP Support sees theirs, etc.

### 2.6 — Validate and Endorse

1. **Build a test report** in Power BI to verify:
   - Measures return expected values
   - Relationships filter correctly
   - Inactive relationships activate properly with `USERELATIONSHIP()`
   - DirectLake mode is working (check for fallback warnings)
2. **Endorse the semantic model:**
   - In the workspace, select the model → **Endorsement** → **Certified** (requires admin approval) or **Promoted**.
   - This signals to downstream consumers (including the ontology) that this is the approved, governed model.

---

## Phase 3: Design the Ontology

With the semantic model validated and endorsed, you now layer an ontology on top to add graph-shaped relationships and semantic descriptions that power Copilot Studio's natural language understanding.

### Why Both a Semantic Model and an Ontology?

| Layer | What It Provides | Best For |
|---|---|---|
| Semantic Model | Star schema, DAX measures, RLS, governance | Aggregations, KPIs, dashboards, Copilot in Power BI |
| Ontology | Entity-relationship graph, semantic descriptions, graph traversal | Natural language Q&A, multi-hop relationship queries, Copilot Studio data agent |

The ontology maps to the **same Gold tables** as the semantic model. It does not duplicate data — it adds a graph interpretation and rich descriptions that the AI agent uses to resolve questions.

### Core Design Principles

1. **Model the business, not the database.** ServiceNow has 1,000+ tables. Your ontology should represent the 10-15 entities your users actually ask questions about.
2. **Name entities in business language.** Use "Incident" not "fact_incident". Use "Support Engineer" not "sys_user".
3. **Keep relationships directional and meaningful.** "Incident → assigned_to → Support Engineer" reads naturally.
4. **Add semantic descriptions everywhere.** Copilot Studio relies on these to interpret natural language — they are not optional.
5. **Start small, iterate.** Launch with 5-7 core entities. Add more after validating with real user questions.

### Recommended Entity Scope for ServiceNow

**Start with these (MVP):**
- Incident
- Configuration Item (CI)
- User (Support Engineer)
- User Group (Support Team)
- Change Request

**Add after MVP validation:**
- Problem
- Knowledge Article
- Service Catalog Request
- Location
- Service (business service CI subtype)

---

## Phase 4: Define Entities

### Entity: Incident

| Property | Source Column | Type | Description |
|---|---|---|---|
| `id` (key) | `fact_incident.sys_id` | String | Unique identifier |
| `number` (display) | `fact_incident.number` | String | Human-readable incident number (e.g., INC0012345) |
| `short_description` | `fact_incident.short_description` | String | Brief summary of the issue |
| `state` | `fact_incident.state` | String | Current lifecycle state: New, In Progress, On Hold, Resolved, Closed |
| `priority` | `fact_incident.priority` | Integer | Urgency × Impact score: 1=Critical, 2=High, 3=Medium, 4=Low |
| `category` | `fact_incident.category` | String | Service category: Hardware, Software, Network, Database, etc. |
| `opened_at` | `fact_incident.opened_at` | DateTime | When the incident was created |
| `resolved_at` | `fact_incident.resolved_at` | DateTime | When the incident was resolved (null if still open) |
| `resolution_hours` | `fact_incident.resolution_hours` | Decimal | Computed: hours between opened_at and resolved_at |
| `is_open` | Computed | Boolean | `state IN ('New', 'In Progress', 'On Hold')` |
| `is_sla_breached` | `fact_incident.is_sla_breached` | Boolean | Whether the incident exceeded its SLA target |

**Semantic description:**
> "An Incident is a record of an unplanned disruption or degradation of an IT service. Incidents are reported by end users or monitoring systems and are assigned to support engineers for resolution. Priority 1 (P1) incidents are critical and affect many users. Priority 4 (P4) incidents are low impact."

### Entity: Configuration Item (CI)

| Property | Source Column | Type | Description |
|---|---|---|---|
| `id` (key) | `dim_ci.sys_id` | String | Unique identifier |
| `name` (display) | `dim_ci.name` | String | CI name (e.g., "prod-sql-01", "SAP ERP") |
| `ci_class` | `dim_ci.sys_class_name` | String | CMDB class: Server, Application, Database, Network Gear, Business Service |
| `operational_status` | `dim_ci.operational_status` | String | Operational, Non-Operational, Retired, Under Maintenance |
| `environment` | `dim_ci.environment` | String | Production, Staging, Development, Test |
| `business_criticality` | `dim_ci.business_criticality` | String | Most Critical, Critical, Less Critical, Non-Critical |

**Semantic description:**
> "A Configuration Item (CI) is an IT asset or service tracked in the CMDB. CIs include physical servers, virtual machines, applications, databases, network devices, and business services. Each CI has an operational status and is classified by its business criticality."

### Entity: User (Support Engineer)

| Property | Source Column | Type | Description |
|---|---|---|---|
| `id` (key) | `dim_user.sys_id` | String | Unique identifier |
| `name` (display) | `dim_user.name` | String | Full name |
| `email` | `dim_user.email` | String | Email address |
| `title` | `dim_user.title` | String | Job title |
| `department` | `dim_user.department` | String | Department name |
| `is_active` | `dim_user.active` | Boolean | Whether the user account is active |

**Semantic description:**
> "A User represents a person in the organization. Users can be support engineers who resolve incidents, managers who approve changes, or end users who report issues. The 'assigned_to' field on incidents and change requests points to the responsible user."

### Entity: User Group (Support Team)

| Property | Source Column | Type | Description |
|---|---|---|---|
| `id` (key) | `dim_user_group.sys_id` | String | Unique identifier |
| `name` (display) | `dim_user_group.name` | String | Group name (e.g., "Network Operations", "SAP Support") |
| `description` | `dim_user_group.description` | String | Purpose of the group |
| `type` | `dim_user_group.type` | String | Group type |

**Semantic description:**
> "A User Group (also called a Support Team or Assignment Group) is a team of users responsible for a specific area of IT support. Incidents and change requests are assigned to groups, and a specific user within the group takes ownership."

### Entity: Change Request

| Property | Source Column | Type | Description |
|---|---|---|---|
| `id` (key) | `fact_change_request.sys_id` | String | Unique identifier |
| `number` (display) | `fact_change_request.number` | String | Change request number (e.g., CHG0005432) |
| `short_description` | `fact_change_request.short_description` | String | Brief summary of the change |
| `type` | `fact_change_request.type` | String | Normal, Standard, Emergency |
| `state` | `fact_change_request.state` | String | New, Assess, Authorize, Scheduled, Implement, Review, Closed |
| `risk` | `fact_change_request.risk` | String | High, Medium, Low |
| `start_date` | `fact_change_request.start_date` | DateTime | Planned start |
| `end_date` | `fact_change_request.end_date` | DateTime | Planned end |
| `approval_status` | `fact_change_request.approval` | String | Requested, Approved, Rejected |

**Semantic description:**
> "A Change Request is a formal proposal to modify an IT system, service, or configuration item. Changes go through an approval workflow and are classified by risk level. Emergency changes bypass normal approval but require post-implementation review."

---

## Phase 5: Define Relationships

### Core Relationships

| Relationship Name | From Entity | To Entity | Cardinality | Source Mapping | Description |
|---|---|---|---|---|---|
| `assigned_to` | Incident | User | Many-to-One | `fact_incident.assigned_to_id` → `dim_user.sys_id` | The support engineer responsible for resolving this incident |
| `assignment_group` | Incident | User Group | Many-to-One | `fact_incident.assignment_group_id` → `dim_user_group.sys_id` | The support team this incident is assigned to |
| `affects_ci` | Incident | Configuration Item | Many-to-One | `fact_incident.cmdb_ci_id` → `dim_ci.sys_id` | The configuration item affected by this incident |
| `opened_by` | Incident | User | Many-to-One | `fact_incident.opened_by_id` → `dim_user.sys_id` | The user who reported this incident |
| `requested_by` | Change Request | User | Many-to-One | `fact_change_request.requested_by_id` → `dim_user.sys_id` | The person who submitted this change request |
| `assigned_to` | Change Request | User | Many-to-One | `fact_change_request.assigned_to_id` → `dim_user.sys_id` | The engineer implementing this change |
| `targets_ci` | Change Request | Configuration Item | Many-to-One | `fact_change_request.cmdb_ci_id` → `dim_ci.sys_id` | The CI being modified by this change |
| `member_of` | User | User Group | Many-to-Many | Via `bridge_user_group_member` | Groups that this user belongs to |
| `depends_on` | Configuration Item | Configuration Item | Many-to-Many | Via `bridge_ci_relationship` (type = 'Depends on') | CI dependency — upstream service this CI relies on |
| `used_by` | Configuration Item | Configuration Item | Many-to-Many | Via `bridge_ci_relationship` (type = 'Used by') | CI usage — downstream services consuming this CI |

### Relationship Diagram

```
                    ┌─────────────┐
         opened_by  │             │  member_of    ┌─────────────┐
        ┌──────────▶│    User     │◀─────────────▶│  User Group │
        │           │             │               └──────▲──────┘
        │           └──────▲──────┘                      │
        │                  │ assigned_to          assignment_group
        │                  │                             │
  ┌─────┴──────┐           │                    ┌────────┴──────┐
  │            │───────────┘                    │               │
  │  Incident  │                                │  Incident     │
  │            │──────────────────────────┐      └───────────────┘
  └─────┬──────┘                         │
        │ affects_ci                     │
        ▼                               │
  ┌─────────────┐    depends_on         │
  │   Config    │◀──────────────┐       │
  │   Item (CI) │               │       │
  │             │───────────────┘       │
  └──────▲──────┘                       │
         │ targets_ci                   │
         │                              │
  ┌──────┴──────┐     requested_by      │
  │   Change    │──────────────────────▶│
  │   Request   │                  (to User)
  └─────────────┘
```

### Many-to-Many Relationship Setup

For relationships that go through bridge tables, configure them in two steps:

**CI Dependencies (via `bridge_ci_relationship`):**

```
bridge_ci_relationship
├── parent_sys_id  →  dim_ci.sys_id  (the CI that depends on another)
├── child_sys_id   →  dim_ci.sys_id  (the CI being depended upon)
└── type           →  filter: 'Depends on::Used by'
```

**User Group Membership (via `bridge_user_group_member`):**

```
bridge_user_group_member
├── user_sys_id   →  dim_user.sys_id
└── group_sys_id  →  dim_user_group.sys_id
```

---

## Phase 6: Add Semantic Descriptions

Semantic descriptions are the single most important factor in how well Copilot Studio understands and answers questions. Write them as if explaining to a new employee.

### Rules for Writing Descriptions

1. **Explain what the entity/property represents in business terms** — not database terms.
2. **Include common synonyms.** If users say "ticket" when they mean "incident," note that.
3. **Clarify value ranges.** For `priority`, state that 1 = Critical and 4 = Low.
4. **Describe null semantics.** "resolved_at is null when the incident is still open."
5. **Call out common questions.** "Users often ask about open P1 incidents or average resolution time."

### Example Descriptions

**Entity-level:**

| Entity | Description |
|---|---|
| Incident | An Incident (also called a ticket or case) is a record of an unplanned IT service disruption. Users frequently ask: how many are open, what is the average resolution time, and which CIs have the most incidents. |
| Configuration Item | A Configuration Item (CI) is any IT asset tracked in the CMDB — servers, applications, databases, or business services. CIs are connected through dependency relationships. |
| Change Request | A Change Request (CR or change) is a formal proposal to modify an IT system. Changes are classified as Normal, Standard, or Emergency and go through an approval workflow. |

**Property-level (examples):**

| Entity.Property | Description |
|---|---|
| Incident.priority | Priority indicates severity. 1 = Critical (major outage, many users affected). 2 = High (significant impact). 3 = Medium (limited impact). 4 = Low (minor issue). When users ask about "P1" or "critical" incidents, they mean priority = 1. |
| Incident.state | Lifecycle state of the incident. "New" = just created. "In Progress" = being worked on. "On Hold" = waiting for information. "Resolved" = fix applied. "Closed" = confirmed resolved. An incident is considered "open" if its state is New, In Progress, or On Hold. |
| Incident.resolution_hours | The number of hours between when the incident was opened and when it was resolved. Null if the incident is still open. Useful for measuring team performance and SLA compliance. |
| CI.operational_status | Current state of the CI. "Operational" = running normally. "Non-Operational" = down. "Under Maintenance" = planned downtime. "Retired" = decommissioned. |

---

## Phase 7: Build and Validate in Fabric IQ

### 7.1 — Create the Ontology

1. Navigate to your Fabric workspace.
2. Select **New** → **Ontology** (under the Knowledge Graph / Fabric IQ section).
3. Name it descriptively: `ServiceNow ITSM Ontology`.
4. Select the Lakehouse or Warehouse containing your Gold tables as the data source.

### 7.2 — Add Entity Types

For each entity defined in [Phase 4](#phase-4-define-entities):

1. Click **Add entity type**.
2. Set the **name** (e.g., "Incident").
3. Map to the **source table** (e.g., `fact_incident`).
4. Set the **key property** (e.g., `sys_id`).
5. Set the **display property** (e.g., `number`).
6. Add each **property** and map it to the corresponding column.
7. Paste the **semantic description** into the description field.

### 7.3 — Add Relationships

For each relationship defined in [Phase 5](#phase-5-define-relationships):

1. Click **Add relationship**.
2. Set the **name** (e.g., "assigned_to").
3. Select the **from** and **to** entity types.
4. Map the foreign key columns.
5. For many-to-many relationships, select the bridge table and map both foreign keys.
6. Add a **description** (e.g., "The support engineer currently responsible for resolving this incident").

### 7.4 — Validate the Ontology

Run these validation checks before publishing:

| Check | How | Expected Result |
|---|---|---|
| Key uniqueness | Query each source table for duplicate sys_id values | Zero duplicates |
| Referential integrity | Left join fact → dimension on foreign keys, check for nulls | Nulls only where expected (e.g., unassigned incidents) |
| Property completeness | Count nulls per property | Critical properties (number, state, priority) should be 100% populated |
| Relationship traversal | Sample query: "Incidents → assigned_to → User → member_of → User Group" | Returns valid paths, no orphans |
| Description quality | Read each description out loud | Would a new employee understand it? |

### 7.5 — Test with Natural Language Queries

Before connecting to Copilot Studio, use the Fabric IQ query interface to test:

| Test Query | Expected Behavior |
|---|---|
| "How many open incidents are there?" | Filters to state IN (New, In Progress, On Hold), returns count |
| "Show me P1 incidents assigned to John Smith" | Filters priority = 1, traverses assigned_to relationship |
| "What CIs have the most incidents this month?" | Joins Incident → affects_ci → CI, groups by CI, filters by date |
| "Which services depend on prod-sql-01?" | Traverses depends_on relationship from the named CI |
| "Average resolution time for the Network Operations team" | Traverses assignment_group → User Group, computes average of resolution_hours |
| "Show me emergency changes scheduled for next week" | Filters type = Emergency, date range on start_date |

---

## Phase 8: Expose to Copilot Studio

### 8.1 — Create or Open a Copilot Studio Agent

1. Go to [Copilot Studio](https://copilotstudio.microsoft.com).
2. Create a new agent or open an existing one.
3. Give it a name like "IT Service Desk Assistant".

### 8.2 — Add the Fabric Data Sources

1. In the agent editor, go to **Knowledge** → **Add knowledge**.
2. Select **Fabric** as the data source type.
3. Add both:
   - The **semantic model** (`ServiceNow ITSM Model`) — gives the agent access to DAX measures and pre-validated star schema queries.
   - The **ontology** (`ServiceNow ITSM Ontology`) — gives the agent graph traversal capabilities for relationship-based questions.
4. Review the entity types and measures that will be available to the agent.

### 8.3 — Configure Topics

Create guided topics for common question patterns:

**Topic: Incident Status**
- Trigger phrases: "incident status", "open incidents", "P1 incidents", "critical incidents"
- Action: Generative answers node pointed at the Fabric ontology
- Fallback: "I couldn't find matching incidents. Can you provide an incident number?"

**Topic: CI Impact Analysis**
- Trigger phrases: "what depends on", "CI impact", "downstream services", "affected systems"
- Action: Graph traversal through depends_on/used_by relationships
- Fallback: "I couldn't find that configuration item. Please check the CI name."

**Topic: Change Schedule**
- Trigger phrases: "upcoming changes", "change schedule", "emergency changes", "changes this week"
- Action: Filter change requests by date range and type

### 8.4 — Test the Agent

Use the Copilot Studio test pane to validate:

- [ ] Simple counts ("How many open incidents?")
- [ ] Filtered queries ("P1 incidents in the last 7 days")
- [ ] Relationship traversal ("Who is assigned to INC0012345?")
- [ ] Multi-hop traversal ("What team handles incidents for prod-sql-01?")
- [ ] Aggregations ("Average resolution time by priority")
- [ ] Temporal queries ("Incidents opened this week vs last week")

### 8.5 — Publish

1. Set up authentication (Azure AD SSO recommended).
2. Choose channels: Microsoft Teams, web chat, or custom.
3. Publish the agent.
4. Monitor usage in Copilot Studio Analytics.

---

## Best Practices

### Semantic Model

- **Build the semantic model before the ontology.** It forces you to validate data types, relationships, and business logic in a well-understood tool (Power BI) before exposing to AI.
- **Use DirectLake mode** for near-real-time performance without data duplication.
- **Define all business metrics as DAX measures.** This ensures Copilot Studio uses the same formulas as Power BI reports — no conflicting answers.
- **Add descriptions to every table and measure.** These descriptions carry through to Copilot and dramatically improve natural language accuracy.
- **Endorse/certify the model** before building the ontology on top. This establishes governance and signals that the model is the approved source of truth.
- **Mark duplicate relationships as inactive** and use `USERELATIONSHIP()` in DAX. Don't create ambiguous active paths.

### Data Layer

- **Always build a Gold layer.** Never point the ontology at raw ServiceNow tables — they contain internal system columns, encoded values, and inconsistent types.
- **Resolve sys_id references in the Gold layer.** Don't make the ontology or Copilot try to join on opaque IDs.
- **Pre-compute common metrics** (resolution_hours, is_sla_breached, is_open) as columns in Gold tables rather than relying on runtime computation.
- **Partition fact tables by date** for query performance on time-filtered questions.

### Ontology Design

- **Fewer entities, richer descriptions.** An ontology with 7 well-described entities outperforms one with 30 poorly described entities.
- **Use business names, not table names.** "Support Engineer" not "sys_user". "Support Team" not "sys_user_group".
- **Include synonyms in descriptions.** "An Incident (also called a ticket, case, or issue)..."
- **Document null semantics.** "resolved_at is null when the incident has not been resolved yet."
- **Test with real user questions** before adding more entities. What do support managers actually ask?

### Relationships

- **Name relationships as verbs or verb phrases.** "assigned_to", "affects_ci", "depends_on" — not "incident_user_link".
- **Always set cardinality correctly.** Incorrect cardinality leads to wrong aggregation results.
- **Limit relationship depth.** Copilot Studio handles 2-3 hops well. Beyond that, consider pre-computing the path as a flattened property.

### Security and Governance

- **Apply row-level security at the Lakehouse/Warehouse level** if different user groups should see different data.
- **Use Fabric workspace roles** to control who can modify the ontology vs. who can query it.
- **Enable audit logging** on both the Fabric workspace and Copilot Studio agent.
- **Do not expose PII unnecessarily.** Exclude fields like personal phone numbers or addresses unless required.
- **Endorse the ontology** in Fabric so consumers know it is the approved, governed version.

### Performance

- **Use DirectLake mode** for the semantic model to get the lowest query latency.
- **Index foreign key columns** in your Warehouse if using Warehouse (not Lakehouse) as the source.
- **Monitor query patterns** in both Power BI usage metrics and Copilot Studio Analytics to optimize the most-hit measures and entity types.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Copilot returns "I don't have information about that" | Missing semantic description or entity not mapped | Add/improve descriptions; verify entity is in the ontology |
| Copilot misinterprets "P1" or "critical" | Description doesn't explain priority values | Add explicit value mapping to the priority property description |
| Relationship traversal returns no results | Referential integrity issue — orphaned foreign keys | Run validation query; clean up null/dangling references in Gold layer |
| Counts are wrong | Duplicate records in source table | Deduplicate in Silver/Gold layer; verify key uniqueness |
| Slow response times | Large table scan without filters | Add date partitioning; pre-aggregate common metrics |
| "Open incidents" includes resolved ones | `is_open` computed property logic is wrong | Verify the state values used in the computation match your ServiceNow config |
| Agent can't answer multi-hop questions | Relationship chain too deep or missing intermediate entity | Add the missing entity; or pre-compute the flattened result as a property |

---

## Appendix: ServiceNow State Value Reference

### Incident States

| Value | Label | Considered "Open"? |
|---|---|---|
| 1 | New | Yes |
| 2 | In Progress | Yes |
| 3 | On Hold | Yes |
| 6 | Resolved | No |
| 7 | Closed | No |
| 8 | Canceled | No |

### Change Request States

| Value | Label |
|---|---|
| -5 | New |
| -4 | Assess |
| -3 | Authorize |
| -2 | Scheduled |
| -1 | Implement |
| 0 | Review |
| 3 | Closed |
| 4 | Canceled |

### Priority Values

| Value | Label | Typical SLA |
|---|---|---|
| 1 | Critical | 1 hour response, 4 hour resolution |
| 2 | High | 4 hour response, 8 hour resolution |
| 3 | Medium | 8 hour response, 24 hour resolution |
| 4 | Low | 24 hour response, 72 hour resolution |

> **Note:** SLA targets vary by organization. Update the above to match your customer's actual SLA definitions.
