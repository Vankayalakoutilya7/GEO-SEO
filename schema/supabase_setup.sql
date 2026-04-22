-- GEO-SEO Database Schema Setup
-- Run this in your Supabase SQL Editor

-- 1. Projects Table
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_url TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Audits Table
CREATE TABLE IF NOT EXISTS audits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    final_score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'RUNNING',
    summary TEXT,
    pdf_url TEXT,
    metrics JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Agent Logs Table (Rich Results v2)
CREATE TABLE IF NOT EXISTS agent_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audit_id UUID REFERENCES audits(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    agent_score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'SUCCESS',
    summary TEXT,
    findings JSONB DEFAULT '[]'::jsonb,
    weaknesses JSONB DEFAULT '[]'::jsonb,
    suggested_code JSONB DEFAULT '[]'::jsonb,
    roadmap JSONB DEFAULT '[]'::jsonb,
    tokens_used INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4. Enable Row Level Security (RLS)
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE audits ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_logs ENABLE ROW LEVEL SECURITY;

-- 4.1 Projects Policies
CREATE POLICY "Allow authenticated select on projects" ON projects FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated insert on projects" ON projects FOR INSERT TO authenticated WITH CHECK (true);
-- Restricted: No public DELETE or UPDATE on projects via API

-- 4.2 Audits Policies
CREATE POLICY "Allow authenticated select on audits" ON audits FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated insert on audits" ON audits FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "Allow authenticated update on audits" ON audits FOR UPDATE TO authenticated 
USING (true) 
WITH CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED', 'PARTIAL'));

-- 4.3 Agent Logs Policies
CREATE POLICY "Allow authenticated select on agent_logs" ON agent_logs FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow authenticated insert on agent_logs" ON agent_logs FOR INSERT TO authenticated WITH CHECK (true);
-- Restricted: Agent logs are immutable once written

-- 5. Storage Buckets
-- Note: You must create the 'reports' bucket manually in the Supabase Dashboard
-- or use the Supabase Storage API to create it if you have appropriate permissions.
-- Make sure the 'reports' bucket is set to PUBLIC if you want the PDF links to work directly.
