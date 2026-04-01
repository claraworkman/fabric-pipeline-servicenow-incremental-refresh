# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "04440b2f-5b2d-4c7c-99ab-3261eb36365b",
# META       "default_lakehouse_name": "servicenow_data",
# META       "default_lakehouse_workspace_id": "30b4a580-14af-4752-8037-254926ff6c2c",
# META       "known_lakehouses": [
# META         {
# META           "id": "04440b2f-5b2d-4c7c-99ab-3261eb36365b"
# META         }
# META       ]
# META     }
# META   }
# META }

# CELL ********************

# ServiceNow Watermark Check
#Queries the Lakehouse table for the maximum `sys_updated_on` value and returns it to the pipeline.

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Parameter injected by the pipeline ForEach activity
table_name = "incident"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

from datetime import datetime, timedelta

try:
    df = spark.sql(f"SELECT MAX(sys_updated_on) AS watermark FROM servicenow_data.{table_name}")
    watermark = df.collect()[0]["watermark"]
except:
    watermark = None

if watermark is None:
    watermark = "1970-01-01 00:00:00"
else:
    # Add 1 second to avoid re-reading the last record due to sub-second precision
    dt = datetime.strptime(str(watermark)[:19], "%Y-%m-%d %H:%M:%S")
    watermark = (dt + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

mssparkutils.notebook.exit(str(watermark))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
