-- Nexora Database Schema - SQLite Version
-- Version: 3.0 | Updated: 3 October 2026

-- ============================================================
-- Core Tables
-- ============================================================

-- Workspaces (sample repositories)
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    repository_url VARCHAR(500),
    repository_type VARCHAR(50) DEFAULT 'python',
    initial_commit_hash VARCHAR(64),
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Repository snapshots (pinned revisions for runs)
CREATE TABLE IF NOT EXISTS repository_snapshots (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    commit_hash VARCHAR(64) NOT NULL,
    branch_name VARCHAR(255) DEFAULT 'main',
    snapshot_path TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, commit_hash)
);

-- Budget profiles (demo, standard, etc.)
CREATE TABLE IF NOT EXISTS budget_profiles (
    id TEXT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    max_steps INTEGER NOT NULL DEFAULT 10,
    max_tool_calls INTEGER NOT NULL DEFAULT 20,
    max_retries INTEGER NOT NULL DEFAULT 1,
    timeout_seconds INTEGER NOT NULL DEFAULT 300,
    max_input_tokens INTEGER NOT NULL DEFAULT 8000,
    max_output_tokens INTEGER NOT NULL DEFAULT 2000,
    is_default BOOLEAN DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Model registry
CREATE TABLE IF NOT EXISTS model_registry (
    id TEXT PRIMARY KEY,
    model_id VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    provider VARCHAR(100) NOT NULL DEFAULT 'nebius',
    tier VARCHAR(50), -- nano, super, ultra
    context_capacity INTEGER NOT NULL,
    max_output_tokens INTEGER NOT NULL,
    supports_tools BOOLEAN DEFAULT 1,
    supports_reasoning BOOLEAN DEFAULT 0,
    is_enabled BOOLEAN DEFAULT 1,
    verification_date DATETIME,
    terms_reviewed BOOLEAN DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Runs (main execution records)
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    snapshot_id TEXT REFERENCES repository_snapshots(id) ON DELETE SET NULL,
    budget_profile_id TEXT NOT NULL REFERENCES budget_profiles(id),
    task_text TEXT NOT NULL,
    task_hash VARCHAR(64) NOT NULL,
    routing_mode VARCHAR(50) NOT NULL DEFAULT 'auto', -- auto, fixed
    requested_model_id TEXT REFERENCES model_registry(id),
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    current_stage VARCHAR(100),
    steps_completed INTEGER DEFAULT 0,
    tool_calls_count INTEGER DEFAULT 0,
    retries_count INTEGER DEFAULT 0,
    input_tokens_used INTEGER DEFAULT 0,
    output_tokens_used INTEGER DEFAULT 0,
    total_elapsed_ms INTEGER DEFAULT 0,
    started_at DATETIME,
    completed_at DATETIME,
    error_message TEXT,
    result_summary TEXT, -- JSON as TEXT for SQLite
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Run events (state transitions and lifecycle)
CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    stage VARCHAR(100),
    message TEXT,
    event_metadata TEXT, -- JSON as TEXT; "metadata" is reserved on declarative models
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Task analysis results
CREATE TABLE IF NOT EXISTS task_analyses (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    objective TEXT NOT NULL,
    constraints TEXT NOT NULL DEFAULT '[]', -- JSON as TEXT
    acceptance_tests TEXT NOT NULL DEFAULT '[]',
    risk_class VARCHAR(50) NOT NULL,
    likely_artifacts TEXT NOT NULL DEFAULT '[]',
    proposed_capabilities TEXT NOT NULL DEFAULT '[]',
    analyzer_version VARCHAR(50),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Security decisions
CREATE TABLE IF NOT EXISTS security_decisions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    decision VARCHAR(50) NOT NULL, -- allowed, blocked, needs_approval
    reason_codes TEXT NOT NULL DEFAULT '[]',
    provenance_summary TEXT NOT NULL DEFAULT '{}',
    injection_findings TEXT NOT NULL DEFAULT '[]',
    risk_level VARCHAR(50),
    gateway_version VARCHAR(50),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Plans
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    hypothesis TEXT NOT NULL,
    candidate_files TEXT NOT NULL DEFAULT '[]',
    candidate_symbols TEXT NOT NULL DEFAULT '[]',
    tool_sequence TEXT NOT NULL DEFAULT '[]',
    test_command VARCHAR(500),
    stop_conditions TEXT NOT NULL DEFAULT '[]',
    estimated_tokens INTEGER,
    estimated_time_seconds INTEGER,
    planner_version VARCHAR(50),
    is_accepted BOOLEAN DEFAULT 0,
    accepted_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Context packages (what was sent to the model)
CREATE TABLE IF NOT EXISTS context_packages (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    model_id TEXT REFERENCES model_registry(id),
    included_files TEXT NOT NULL DEFAULT '[]',
    omitted_categories TEXT NOT NULL DEFAULT '[]',
    ranking_reasons TEXT NOT NULL DEFAULT '{}',
    cache_hits INTEGER DEFAULT 0,
    estimated_input_tokens INTEGER,
    actual_input_tokens INTEGER,
    compression_ratio REAL,
    context_optimizer_version VARCHAR(50),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Tool requests from model
CREATE TABLE IF NOT EXISTS tool_requests (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    request_id VARCHAR(100) NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    arguments TEXT NOT NULL, -- JSON as TEXT
    provenance VARCHAR(50) NOT NULL, -- model, system, user
    expected_risk VARCHAR(50),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Policy decisions (the core security boundary)
CREATE TABLE IF NOT EXISTS policy_decisions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    tool_request_id TEXT REFERENCES tool_requests(id) ON DELETE SET NULL,
    capability VARCHAR(100) NOT NULL,
    decision VARCHAR(50) NOT NULL, -- ALLOW, ALLOW_WITH_MONITORING, REQUIRE_APPROVAL, DENY, QUARANTINE
    reason_codes TEXT NOT NULL DEFAULT '[]',
    risk_level VARCHAR(50),
    normalized_arguments TEXT,
    target_path TEXT,
    policy_version VARCHAR(50),
    engine_version VARCHAR(50),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Approvals
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    policy_decision_id TEXT NOT NULL REFERENCES policy_decisions(id) ON DELETE CASCADE,
    scope_description TEXT NOT NULL,
    expires_at DATETIME NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- pending, approved, rejected, expired
    approver_id VARCHAR(255),
    decided_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Tool executions (sandbox results)
CREATE TABLE IF NOT EXISTS tool_executions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    tool_request_id TEXT REFERENCES tool_requests(id) ON DELETE SET NULL,
    policy_decision_id TEXT REFERENCES policy_decisions(id) ON DELETE SET NULL,
    tool_name VARCHAR(100) NOT NULL,
    arguments TEXT NOT NULL, -- JSON as TEXT
    stdout TEXT,
    stderr TEXT,
    exit_code INTEGER,
    duration_ms INTEGER,
    sandbox_id VARCHAR(255),
    execution_status VARCHAR(50), -- success, failure, timeout, error
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Validator/Critic findings
CREATE TABLE IF NOT EXISTS validation_findings (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    check_type VARCHAR(100) NOT NULL, -- patch_applies, syntax, lint, targeted_tests, broader_tests, security_regression, diff_review
    status VARCHAR(50) NOT NULL, -- pass, fail, warning, skipped
    message TEXT,
    details TEXT, -- JSON as TEXT
    critic_version VARCHAR(50),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Final results
CREATE TABLE IF NOT EXISTS run_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    final_status VARCHAR(50) NOT NULL, -- completed, failed, blocked, cancelled, timeout_failed
    patch_hash VARCHAR(64),
    patch_content TEXT,
    test_summary TEXT, -- JSON as TEXT
    critic_findings TEXT, -- JSON as TEXT
    policy_decisions_summary TEXT, -- JSON as TEXT
    blocked_actions TEXT, -- JSON as TEXT
    limitations TEXT, -- JSON as TEXT
    model_used_id TEXT REFERENCES model_registry(id),
    attempts INTEGER DEFAULT 1,
    total_tool_calls INTEGER DEFAULT 0,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_elapsed_ms INTEGER DEFAULT 0,
    evidence_report TEXT, -- JSON as TEXT
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Audit log (append-only, hash-chained)
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    event_index INTEGER NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_data TEXT NOT NULL, -- JSON as TEXT
    previous_hash VARCHAR(64),
    current_hash VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, event_index)
);

-- Loop detection records
CREATE TABLE IF NOT EXISTS loop_detections (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    action_hash VARCHAR(64) NOT NULL,
    action_type VARCHAR(100) NOT NULL,
    normalized_command TEXT,
    target_path TEXT,
    result_class VARCHAR(50),
    attempt_count INTEGER DEFAULT 1,
    last_attempt_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_runs_workspace_id ON runs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_requests_run_id ON tool_requests(run_id);
CREATE INDEX IF NOT EXISTS idx_policy_decisions_run_id ON policy_decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_executions_run_id ON tool_executions(run_id);
CREATE INDEX IF NOT EXISTS idx_validation_findings_run_id ON validation_findings(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_run_id ON audit_events(run_id);
CREATE INDEX IF NOT EXISTS idx_loop_detections_run_id ON loop_detections(run_id);
CREATE INDEX IF NOT EXISTS idx_approvals_run_id ON approvals(run_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);

-- ============================================================
-- Initial Data
-- ============================================================

-- Default budget profiles
INSERT OR IGNORE INTO budget_profiles (id, name, description, max_steps, max_tool_calls, max_retries, timeout_seconds, max_input_tokens, max_output_tokens, is_default) VALUES
('308f5d2a-4826-444d-9630-e47d42e4b13c', 'demo', 'Tight limits for hackathon demo', 10, 20, 1, 300, 8000, 2000, 1),
('96224c1f-2266-4f0a-bf1f-5c626acb9beb', 'standard', 'Standard profile for production-like runs', 40, 80, 3, 900, 50000, 12000, 0);

-- Workspaces are created dynamically by seed_demo_data.py or user action
-- No hardcoded sample workspaces

-- Model registry entries (candidate tiers - enabled after verification)
INSERT OR IGNORE INTO model_registry (id, model_id, display_name, provider, tier, context_capacity, max_output_tokens, supports_tools, supports_reasoning, is_enabled, verification_date, terms_reviewed) VALUES
('4f6209a0-c47f-4653-aa00-9a45893dfe46', 'deepseek-ai/DeepSeek-R1-0528', 'DeepSeek R1 0528', 'nebius', 'ultra', 128000, 4096, 1, 1, 0, NULL, 0),
('6f6163e3-655c-487a-9467-61d2ded37000', 'meta-llama/Meta-Llama-3.1-70B-Instruct', 'Meta Llama 3.1 70B Instruct', 'nebius', 'super', 131072, 4096, 1, 0, 0, NULL, 0),
('ed8921f0-8139-477c-acfd-e5434e62a522', 'meta-llama/Meta-Llama-3.1-8B-Instruct', 'Meta Llama 3.1 8B Instruct', 'nebius', 'nano', 131072, 2048, 1, 0, 0, NULL, 0);
