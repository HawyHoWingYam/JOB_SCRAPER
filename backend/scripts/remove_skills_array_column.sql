-- Migration: Remove skills ARRAY column from jobs table
-- Run this AFTER batch enrichment completes and data is verified in relational tables

-- Drop the skills ARRAY column
ALTER TABLE jobs DROP COLUMN IF EXISTS skills;

-- Verify the column is removed
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'jobs'
ORDER BY ordinal_position;
