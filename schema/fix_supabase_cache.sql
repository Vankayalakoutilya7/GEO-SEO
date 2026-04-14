-- SUPABASE SCHEMA CACHE RELOAD
-- Run this in your Supabase SQL Editor to resolve "Schema Stale" (PGRST204) errors.
-- This forces PostgREST to refresh its internal column mapping.

NOTIFY pgrst, 'reload schema';

-- Verification: After running, your GEO-SEO app should be able to 
-- perform "Full Saves" without falling back to Legacy/Atomic modes.
