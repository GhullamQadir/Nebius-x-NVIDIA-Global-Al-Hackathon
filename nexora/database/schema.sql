-- Nexora Database Schema
-- PostgreSQL schema for the Nexora coding agent
-- Version: 3.0 | Updated: 3 October 2026

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- Core Tables
-- ============================================================

-- Workspaces (sample repositories)
CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    repository_url VARCHAR(500),
    repository_type VARCHAR(50) DEFAULT 'python',
    initial_commit_hash VARCHAR(64),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Repository snapshots (pinned revisions for runs)
CREATE TABLE repository_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    commit_hash VARCHAR(64) NOT NULL,
    branch_name VARCHAR(255) DEFAULT 'main',
    snapshot_path TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(workspace_id, commit_hash)
);

-- Budget profiles (demo, standard, etc.)
CREATE TABLE budget_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    max_steps INTEGER NOT NULL DEFAULT 10,
    max_tool_calls INTEGER NOT NULL DEFAULT 20,
    max_retries INTEGER NOT NULL DEFAULT 1,
    timeout_seconds INTEGER NOT NULL DEFAULT 300,
    max_input_tokens INTEGER NOT NULL DEFAULT 8000,
    max_output_tokens INTEGER NOT NULL DEFAULT 2000,
    is_default BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Model registry
CREATE TABLE model_registry (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_id VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    provider VARCHAR(100) NOT NULL DEFAULT 'nebius',
    tier VARCHAR(50), -- nano, super, ultra
    context_capacity INTEGER NOT NULL,
    max_output_tokens INTEGER NOT NULL,
    supports_tools BOOLEAN DEFAULT true,
    supports_reasoning BOOLEAN DEFAULT false,
    is_enabled BOOLEAN DEFAULT true,
    verification_date TIMESTAMPTZ,
    terms_reviewed BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Runs (main execution records)
CREATE TABLE runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    snapshot_id UUID REFERENCES repository_snapshots(id) ON DELETE SET NULL,
    budget_profile_id UUID NOT NULL REFERENCES budget_profiles(id),
    task_text TEXT NOT NULL,
    task_hash VARCHAR(64) NOT NULL,
    routing_mode VARCHAR(50) NOT NULL DEFAULT 'auto', -- auto, fixed
    requested_model_id UUID REFERENCES model_registry(id),
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    current_stage VARCHAR(100),
    steps_completed INTEGER DEFAULT 0,
    tool_calls_count INTEGER DEFAULT 0,
    retries_count INTEGER DEFAULT 0,
    input_tokens_used INTEGER DEFAULT 0,
    output_tokens_used INTEGER DEFAULT 0,
    total_elapsed_ms INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    result_summary JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Run events (state transitions and lifecycle)
CREATE TABLE run_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    stage VARCHAR(100),
    message TEXT,
    event_metadata JSONB, -- "metadata" is reserved on declarative models
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Task analysis results
CREATE TABLE task_analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    objective TEXT NOT NULL,
    constraints JSONB NOT NULL DEFAULT '[]',
    acceptance_tests JSONB NOT NULL DEFAULT '[]',
    risk_class VARCHAR(50) NOT NULL,
    likely_artifacts JSONB NOT NULL DEFAULT '[]',
    proposed_capabilities JSONB NOT NULL DEFAULT '[]',
    analyzer_version VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Security decisions
CREATE TABLE security_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    decision VARCHAR(50) NOT NULL, -- allowed, blocked, needs_approval
    reason_codes JSONB NOT NULL DEFAULT '[]',
    provenance_summary JSONB NOT NULL DEFAULT '{}',
    injection_findings JSONB NOT NULL DEFAULT '[]',
    risk_level VARCHAR(50),
    gateway_version VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Plans
CREATE TABLE plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    hypothesis TEXT NOT NULL,
    candidate_files JSONB NOT NULL DEFAULT '[]',
    candidate_symbols JSONB NOT NULL DEFAULT '[]',
    tool_sequence JSONB NOT NULL DEFAULT '[]',
    test_command VARCHAR(500),
    stop_conditions JSONB NOT NULL DEFAULT '[]',
    estimated_tokens INTEGER,
    estimated_time_seconds INTEGER,
    planner_version VARCHAR(50),
    is_accepted BOOLEAN DEFAULT false,
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Context packages (what was sent to the model)
CREATE TABLE context_packages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    model_id UUID REFERENCES model_registry(id),
    included_files JSONB NOT NULL DEFAULT '[]',
    omitted_categories JSONB NOT NULL DEFAULT '[]',
    ranking_reasons JSONB NOT NULL DEFAULT '{}',
    cache_hits INTEGER DEFAULT 0,
    estimated_input_tokens INTEGER,
    actual_input_tokens INTEGER,
    compression_ratio NUMERIC(5,2),
    context_optimizer_version VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tool requests from model
CREATE TABLE tool_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    request_id VARCHAR(100) NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    arguments JSONB NOT NULL,
    provenance VARCHAR(50) NOT NULL, -- model, system, user
    expected_risk VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Policy decisions (the core security boundary)
CREATE TABLE policy_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    tool_request_id UUID REFERENCES tool_requests(id) ON DELETE SET NULL,
    capability VARCHAR(100) NOT NULL,
    decision VARCHAR(50) NOT NULL, -- ALLOW, ALLOW_WITH_MONITORING, REQUIRE_APPROVAL, DENY, QUARANTINE
    reason_codes JSONB NOT NULL DEFAULT '[]',
    risk_level VARCHAR(50),
    normalized_arguments JSONB,
    target_path TEXT,
    policy_version VARCHAR(50),
    engine_version VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Approvals
CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    policy_decision_id UUID NOT NULL REFERENCES policy_decisions(id) ON DELETE CASCADE,
    scope_description TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- pending, approved, rejected, expired
    approver_id VARCHAR(255),
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tool executions (sandbox results)
CREATE TABLE tool_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    tool_request_id UUID REFERENCES tool_requests(id) ON DELETE SET NULL,
    policy_decision_id UUID REFERENCES policy_decisions(id) ON DELETE SET NULL,
    tool_name VARCHAR(100) NOT NULL,
    arguments JSONB NOT NULL,
    stdout TEXT,
    stderr TEXT,
    exit_code INTEGER,
    duration_ms INTEGER,
    sandbox_id VARCHAR(255),
    execution_status VARCHAR(50), -- success, failure, timeout, error
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Validator/Critic findings
CREATE TABLE validation_findings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    check_type VARCHAR(100) NOT NULL, -- patch_applies, syntax, lint, targeted_tests, broader_tests, security_regression, diff_review
    status VARCHAR(50) NOT NULL, -- pass, fail, warning, skipped
    message TEXT,
    details JSONB,
    critic_version VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Final results
CREATE TABLE run_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    final_status VARCHAR(50) NOT NULL, -- completed, failed, blocked, cancelled, timeout_failed
    patch_hash VARCHAR(64),
    patch_content TEXT,
    test_summary JSONB,
    critic_findings JSONB,
    policy_decisions_summary JSONB,
    blocked_actions JSONB,
    limitations JSONB,
    model_used_id UUID REFERENCES model_registry(id),
    attempts INTEGER DEFAULT 1,
    total_tool_calls INTEGER DEFAULT 0,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_elapsed_ms INTEGER DEFAULT 0,
    evidence_report JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Audit log (append-only, hash-chained)
CREATE TABLE audit_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    event_index INTEGER NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB NOT NULL,
    previous_hash VARCHAR(64),
    current_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(run_id, event_index)
);

-- Loop detection records
CREATE TABLE loop_detections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    action_hash VARCHAR(64) NOT NULL,
    action_type VARCHAR(100) NOT NULL,
    normalized_command TEXT,
    target_path TEXT,
    result_class VARCHAR(50),
    attempt_count INTEGER DEFAULT 1,
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_runs_workspace_id ON runs(workspace_id);
CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_runs_created_at ON runs(created_at DESC);
CREATE INDEX idx_run_events_run_id ON run_events(run_id);
CREATE INDEX idx_tool_requests_run_id ON tool_requests(run_id);
CREATE INDEX idx_policy_decisions_run_id ON policy_decisions(run_id);
CREATE INDEX idx_tool_executions_run_id ON tool_executions(run_id);
CREATE INDEX idx_validation_findings_run_id ON validation_findings(run_id);
CREATE INDEX idx_audit_events_run_id ON audit_events(run_id);
CREATE INDEX idx_loop_detections_run_id ON loop_detections(run_id);
CREATE INDEX idx_approvals_run_id ON approvals(run_id);
CREATE INDEX idx_approvals_status ON approvals(status);

-- ============================================================
-- Initial Data
-- ============================================================

-- Default budget profiles
INSERT INTO budget_profiles (name, description, max_steps, max_tool_calls, max_retries, timeout_seconds, max_input_tokens, max_output_tokens, is_default) VALUES
('demo', 'Tight limits for hackathon demo', 10, 20, 1, 300, 8000, 2000, true),
('standard', 'Standard profile for production-like runs', 40, 80, 3, 900, 50000, 12000, false);

-- Workspaces are created dynamically by seed_demo_data.py or user action
-- No hardcoded sample workspaces

-- Model registry entries (candidate tiers - enabled after verification)
INSERT INTO model_registry (model_id, display_name, provider, tier, context_capacity, max_output_tokens, supports_tools, supports_reasoning, is_enabled, verification_date, terms_reviewed) VALUES
('deepseek-ai/DeepSeek-R1-0528', 'DeepSeek R1 0528', 'nebius', 'ultra', 128000, 4096, true, true, false, NULL, false),
('meta-llama/Meta-Llama-3.1-70B-Instruct', 'Meta Llama 3.1 70B Instruct', 'nebius', 'super', 131072, 4096, true, false, false, NULL, false),
('meta-llama/Meta-Llama-3.1-8B-Instruct', 'Meta Llama 3.1 8B Instruct', 'nebius', 'nano', 131072, 2048, true, false, false, NULL, false);