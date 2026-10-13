-- WaferAI 데이터베이스 스키마 (PostgreSQL 16)
-- 마이그레이션 head 8c41e07d2a95 기준 최종 스키마 · 2026-10-13 생성
--
-- 빈 DB 에 이 파일을 실행하면 `alembic upgrade head` 로 만든 DB 와 같은 스키마가 되고,
-- alembic_version 도 head 로 기록되어 이후 마이그레이션을 그대로 이어 적용할 수 있다.
--     psql -v ON_ERROR_STOP=1 -d <DB> -f WaferAI_DB_schema_postgresql.sql
-- 운영 서버는 이 파일이 아니라 마이그레이션으로 스키마를 만든다 (deploy/entrypoint.sh).

BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

CREATE TABLE users (
    employee_id VARCHAR(20) NOT NULL,
    name VARCHAR(50) NOT NULL,
    email VARCHAR(120) NOT NULL,
    department VARCHAR(50),
    role VARCHAR(20) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    password_changed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_active BOOLEAN NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (employee_id),
    UNIQUE (email)
);

CREATE TABLE ai_model (
    model_id SERIAL NOT NULL,
    model_name VARCHAR(80) NOT NULL,
    version VARCHAR(20) NOT NULL,
    file_sha256 VARCHAR(64) NOT NULL,
    backend VARCHAR(20) NOT NULL,
    val_accuracy FLOAT,
    epoch INTEGER,
    is_active BOOLEAN NOT NULL,
    deployed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    split_id VARCHAR(32),
    test_metrics JSON,
    PRIMARY KEY (model_id),
    UNIQUE (file_sha256)
);

CREATE TABLE settings (
    key VARCHAR(40) NOT NULL,
    value JSON NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_by VARCHAR(20),
    PRIMARY KEY (key),
    FOREIGN KEY(updated_by) REFERENCES users (employee_id)
);

CREATE TABLE wafer_result (
    wafer_id VARCHAR(40) NOT NULL,
    filename TEXT,
    input_type VARCHAR(10) NOT NULL,
    input_info JSON,
    wafer_map JSON NOT NULL,
    probabilities JSON NOT NULL,
    final_class VARCHAR(20) NOT NULL,
    decision_path VARCHAR(24) NOT NULL,
    confidence FLOAT NOT NULL,
    defect_ratio FLOAT NOT NULL,
    requires_human_review BOOLEAN NOT NULL,
    model_id INTEGER NOT NULL,
    uploaded_by VARCHAR(20),
    processed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    heatmap_path TEXT,
    PRIMARY KEY (wafer_id),
    FOREIGN KEY(model_id) REFERENCES ai_model (model_id),
    FOREIGN KEY(uploaded_by) REFERENCES users (employee_id)
);

CREATE TABLE review_result (
    review_id SERIAL NOT NULL,
    wafer_id VARCHAR(40) NOT NULL,
    final_class VARCHAR(20) NOT NULL,
    reviewer_id VARCHAR(20) NOT NULL,
    review_memo TEXT NOT NULL,
    reviewed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (review_id),
    FOREIGN KEY(wafer_id) REFERENCES wafer_result (wafer_id),
    FOREIGN KEY(reviewer_id) REFERENCES users (employee_id)
);

CREATE TABLE retrain_job (
    job_id VARCHAR(60) NOT NULL,
    model_type VARCHAR(60) NOT NULL,
    triggered_by VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    review_cutoff TIMESTAMP WITH TIME ZONE NOT NULL,
    new_reviews INTEGER NOT NULL,
    base_model_id INTEGER,
    result_model_id INTEGER,
    note TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (job_id),
    FOREIGN KEY(base_model_id) REFERENCES ai_model (model_id),
    FOREIGN KEY(result_model_id) REFERENCES ai_model (model_id)
);

INSERT INTO alembic_version (version_num) VALUES ('8c41e07d2a95');

COMMIT;
