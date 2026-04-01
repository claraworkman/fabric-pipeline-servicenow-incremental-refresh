CREATE PROCEDURE dbo.usp_UpdateWatermark
    @tableName NVARCHAR(100),
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

