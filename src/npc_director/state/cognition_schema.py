COGNITION_SCHEMA = """
CREATE TABLE IF NOT EXISTS cognition_actors (
 session_id TEXT NOT NULL, npc_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
 sequence INTEGER NOT NULL DEFAULT 0, consolidated_seq INTEGER NOT NULL DEFAULT 0,
 behavior_json TEXT NOT NULL DEFAULT '{"mode_id":"neutral","version":0}',
 PRIMARY KEY(session_id,npc_id));
CREATE TABLE IF NOT EXISTS cognition_sources (
 session_id TEXT NOT NULL, npc_id TEXT NOT NULL, event_id TEXT NOT NULL,
 sequence INTEGER NOT NULL, episode_id TEXT, payload_json TEXT NOT NULL,
 PRIMARY KEY(session_id,npc_id,event_id));
CREATE TABLE IF NOT EXISTS cognition_memories (
 session_id TEXT NOT NULL, npc_id TEXT NOT NULL, memory_id TEXT NOT NULL,
 record_json TEXT NOT NULL, PRIMARY KEY(session_id,npc_id,memory_id));
CREATE TABLE IF NOT EXISTS cognition_links (
 session_id TEXT NOT NULL, npc_id TEXT NOT NULL, source_id TEXT NOT NULL,
 target_id TEXT NOT NULL, relation TEXT NOT NULL,
 PRIMARY KEY(session_id,npc_id,source_id,target_id,relation));
CREATE TABLE IF NOT EXISTS cognition_effects (
 session_id TEXT NOT NULL, npc_id TEXT NOT NULL, effect_id TEXT NOT NULL,
 PRIMARY KEY(session_id,npc_id,effect_id));
CREATE TABLE IF NOT EXISTS cognition_jobs (
 job_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, npc_id TEXT NOT NULL,
 episode_id TEXT, input_revision INTEGER NOT NULL, input_seq INTEGER NOT NULL,
 snapshot_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, claimed_by TEXT, lease_until REAL,
 reservation_id TEXT, usage_json TEXT, last_error TEXT,
 UNIQUE(session_id,npc_id,input_revision));
INSERT OR IGNORE INTO state_schema_versions VALUES (3, 'Owner scoped cognition and maintenance');
"""
