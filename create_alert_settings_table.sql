CREATE TABLE IF NOT EXISTS alert_settings (
    id INTEGER PRIMARY KEY,
    min_quality_score INTEGER NOT NULL DEFAULT 70,
    min_call_duration INTEGER NOT NULL DEFAULT 60,
    max_call_duration INTEGER NOT NULL DEFAULT 1800,
    max_response_time_hours INTEGER NOT NULL DEFAULT 24,
    alert_keywords JSON,
    notify_on_low_quality BOOLEAN NOT NULL DEFAULT 1,
    notify_on_missed_commitment BOOLEAN NOT NULL DEFAULT 1,
    notify_on_keywords BOOLEAN NOT NULL DEFAULT 1,
    notify_on_long_silence BOOLEAN NOT NULL DEFAULT 0,
    send_daily_digest BOOLEAN NOT NULL DEFAULT 1,
    digest_time VARCHAR(5) NOT NULL DEFAULT '09:00',
    working_hours_start VARCHAR(5) NOT NULL DEFAULT '09:00',
    working_hours_end VARCHAR(5) NOT NULL DEFAULT '18:00',
    alert_outside_hours BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Insert default settings
INSERT INTO alert_settings (id) VALUES (1);
