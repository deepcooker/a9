CREATE TABLE IF NOT EXISTS sessions (
  session_id VARCHAR(255) PRIMARY KEY,
  project_id VARCHAR(128) NOT NULL DEFAULT 'a9',
  root_path TEXT NOT NULL,
  status ENUM('running', 'paused', 'blocked', 'complete') NOT NULL,
  current_checkpoint_id VARCHAR(255),
  parent_session_id VARCHAR(255),
  source VARCHAR(64) NOT NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_sessions_parent FOREIGN KEY (parent_session_id) REFERENCES sessions(session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS checkpoints (
  checkpoint_id VARCHAR(255) PRIMARY KEY,
  session_id VARCHAR(255) NOT NULL,
  parent_checkpoint_id VARCHAR(255),
  step INT NOT NULL,
  source VARCHAR(64) NOT NULL,
  status VARCHAR(64) NOT NULL,
  channels JSON NOT NULL,
  updated_channels JSON NOT NULL,
  token_usage JSON NOT NULL,
  evidence_ids JSON NOT NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_checkpoints_session FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
  CONSTRAINT fk_checkpoints_parent FOREIGN KEY (parent_checkpoint_id) REFERENCES checkpoints(checkpoint_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE INDEX checkpoints_session_step_idx ON checkpoints(session_id, step DESC);
CREATE INDEX checkpoints_source_idx ON checkpoints(source);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id VARCHAR(512) PRIMARY KEY,
  session_id VARCHAR(255) NOT NULL,
  checkpoint_id VARCHAR(255) NOT NULL,
  kind VARCHAR(64) NOT NULL,
  path TEXT NOT NULL,
  sha256 CHAR(64) NOT NULL,
  size_bytes BIGINT NOT NULL,
  metadata JSON NOT NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_evidence_checkpoint FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(checkpoint_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE INDEX evidence_session_kind_idx ON evidence(session_id, kind);
CREATE INDEX evidence_checkpoint_idx ON evidence(checkpoint_id);

CREATE TABLE IF NOT EXISTS deep_context_marks (
  mark_id VARCHAR(768) PRIMARY KEY,
  session_id VARCHAR(255) NOT NULL,
  checkpoint_id VARCHAR(255) NOT NULL,
  evidence_id VARCHAR(512),
  kind VARCHAR(64) NOT NULL,
  label VARCHAR(255) NOT NULL,
  value TEXT NOT NULL,
  weight DECIMAL(5,3) NOT NULL DEFAULT 1.0,
  metadata JSON NOT NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  FULLTEXT KEY deep_context_marks_value_ft (value),
  CONSTRAINT fk_deep_marks_checkpoint FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(checkpoint_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE INDEX deep_context_marks_session_kind_idx ON deep_context_marks(session_id, kind);
CREATE INDEX deep_context_marks_label_idx ON deep_context_marks(label);

CREATE TABLE IF NOT EXISTS memories (
  memory_id CHAR(36) PRIMARY KEY,
  project_id VARCHAR(128) NOT NULL DEFAULT 'a9',
  user_id VARCHAR(255),
  agent_id VARCHAR(255),
  run_id VARCHAR(255),
  memory_type VARCHAR(64) NOT NULL,
  memory TEXT NOT NULL,
  confidence DECIMAL(4,3) NOT NULL DEFAULT 0.8,
  evidence_ids JSON NOT NULL,
  supersedes JSON NOT NULL,
  metadata JSON NOT NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  FULLTEXT KEY memories_memory_ft (memory)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE INDEX memories_scope_idx ON memories(project_id, user_id(128), agent_id(128), run_id(128));
CREATE INDEX memories_type_idx ON memories(memory_type);

CREATE TABLE IF NOT EXISTS memory_history (
  history_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  memory_id CHAR(36) NOT NULL,
  action VARCHAR(64) NOT NULL,
  previous_value JSON,
  new_value JSON,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_memory_history_memory FOREIGN KEY (memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
