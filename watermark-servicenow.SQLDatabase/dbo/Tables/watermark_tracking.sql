CREATE TABLE [dbo].[watermark_tracking] (
    [table_name]      NVARCHAR (128) NOT NULL,
    [watermark_value] DATETIME2 (7)  DEFAULT ('1970-01-01 00:00:00') NOT NULL,
    PRIMARY KEY CLUSTERED ([table_name] ASC)
);


GO

