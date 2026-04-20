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

-- 4. Enable Row Level Security (RLS) - Optional: Adjust as needed for your app

-- Create policies for public access (for testing, adjust for production)
CREATE POLICY "Allow public select on projects" ON projects FOR SELECT USING (true);
CREATE POLICY "Allow public insert on projects" ON projects FOR INSERT WITH CHECK (true);

CREATE POLICY "Allow public select on audits" ON audits FOR SELECT USING (true);
CREATE POLICY "Allow public insert on audits" ON audits FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow public update on audits" ON audits FOR UPDATE USING (true);

CREATE POLICY "Allow public select on agent_logs" ON agent_logs FOR SELECT USING (true);
CREATE POLICY "Allow public insert on agent_logs" ON agent_logs FOR INSERT WITH CHECK (true);

-- 5. Storage Buckets
-- Note: You must create the 'reports' bucket manually in the Supabase Dashboard
-- or use the Supabase Storage API to create it if you have appropriate permissions.
-- Make sure the 'reports' bucket is set to PUBLIC if you want the PDF links to work directly.
