-- Initial database schema for SalesBot MVP
-- SQLite optimized schema with proper indexing

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

-- Calls table
CREATE TABLE IF NOT EXISTS calls (
    id CHAR(32) PRIMARY KEY,
    amocrm_call_id VARCHAR(50) UNIQUE NOT NULL,
    amocrm_lead_id VARCHAR(50),
    manager_id INTEGER NOT NULL,
    client_phone VARCHAR(20),
    duration_seconds INTEGER CHECK (duration_seconds >= 0),
    audio_url TEXT,
    transcription_status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    transcription_text TEXT,
    transcription_error TEXT,
    analysis_status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    analysis_result JSON,
    analysis_error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    FOREIGN KEY (manager_id) REFERENCES managers(id)
);

-- Managers table
CREATE TABLE IF NOT EXISTS managers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amocrm_user_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    telegram_chat_id VARCHAR(50) UNIQUE,
    is_active BOOLEAN DEFAULT 1 NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Analysis cache table
CREATE TABLE IF NOT EXISTS analysis_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text_hash VARCHAR(64) UNIQUE NOT NULL,
    analysis_type VARCHAR(50) NOT NULL,
    result JSON NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Reports table
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type VARCHAR(20) NOT NULL,
    manager_id INTEGER,
    date_from DATETIME NOT NULL,
    date_to DATETIME NOT NULL,
    data JSON NOT NULL,
    file_path VARCHAR(500),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    FOREIGN KEY (manager_id) REFERENCES managers(id)
);

-- System logs table
CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    context JSON,
    source VARCHAR(100),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Token storage table
CREATE TABLE IF NOT EXISTS token_storage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service VARCHAR(50) NOT NULL,
    token_type VARCHAR(50) NOT NULL,
    encrypted_token TEXT NOT NULL,
    expires_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE(service, token_type)
);

-- Indexes for better performance
CREATE INDEX IF NOT EXISTS idx_calls_amocrm_id ON calls(amocrm_call_id);
CREATE INDEX IF NOT EXISTS idx_calls_lead_id ON calls(amocrm_lead_id);
CREATE INDEX IF NOT EXISTS idx_calls_manager_created ON calls(manager_id, created_at);
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(transcription_status, analysis_status);
CREATE INDEX IF NOT EXISTS idx_calls_client_phone ON calls(client_phone);

CREATE INDEX IF NOT EXISTS idx_managers_amocrm_id ON managers(amocrm_user_id);
CREATE INDEX IF NOT EXISTS idx_managers_telegram ON managers(telegram_chat_id);
CREATE INDEX IF NOT EXISTS idx_managers_active ON managers(is_active, created_at);

CREATE INDEX IF NOT EXISTS idx_cache_hash ON analysis_cache(text_hash);
CREATE INDEX IF NOT EXISTS idx_cache_type_expires ON analysis_cache(analysis_type, expires_at);

CREATE INDEX IF NOT EXISTS idx_reports_type ON reports(report_type);
CREATE INDEX IF NOT EXISTS idx_reports_manager_type ON reports(manager_id, report_type);
CREATE INDEX IF NOT EXISTS idx_reports_date_range ON reports(date_from, date_to);

CREATE INDEX IF NOT EXISTS idx_logs_level_created ON system_logs(level, created_at);
CREATE INDEX IF NOT EXISTS idx_logs_source_created ON system_logs(source, created_at);

CREATE INDEX IF NOT EXISTS idx_tokens_service ON token_storage(service);
CREATE INDEX IF NOT EXISTS idx_tokens_expires ON token_storage(expires_at);

-- Triggers for updated_at
CREATE TRIGGER IF NOT EXISTS update_calls_updated_at 
    AFTER UPDATE ON calls
    BEGIN
        UPDATE calls SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

CREATE TRIGGER IF NOT EXISTS update_managers_updated_at 
    AFTER UPDATE ON managers
    BEGIN
        UPDATE managers SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

CREATE TRIGGER IF NOT EXISTS update_analysis_cache_updated_at 
    AFTER UPDATE ON analysis_cache
    BEGIN
        UPDATE analysis_cache SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

CREATE TRIGGER IF NOT EXISTS update_reports_updated_at 
    AFTER UPDATE ON reports
    BEGIN
        UPDATE reports SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

CREATE TRIGGER IF NOT EXISTS update_system_logs_updated_at 
    AFTER UPDATE ON system_logs
    BEGIN
        UPDATE system_logs SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

CREATE TRIGGER IF NOT EXISTS update_token_storage_updated_at 
    AFTER UPDATE ON token_storage
    BEGIN
        UPDATE token_storage SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;