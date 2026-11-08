-- ============================================================
-- Capa estructurada del brain (DuckDB). DERIVADA: se reconstruye
-- con `dh build-db` desde skills.yaml, events/*.jsonl,
-- projects/*.md y jobs/*.md. Fase 3: migrar a un proyecto dbt
-- (staging -> intermediate -> marts) con tests y docs.
-- ============================================================

-- Dimensión: skills (desde skills.yaml)
CREATE TABLE skills (
    skill_id      VARCHAR PRIMARY KEY,   -- ej: 'sql_window_functions'
    domain        VARCHAR NOT NULL,      -- analytics_engineering | data_engineering | ai_engineering | bi | data_governance | ml ...
    name          VARCHAR NOT NULL,
    level         INTEGER NOT NULL,      -- 0..5 (ver rúbrica en skills.yaml)
    target_level  INTEGER NOT NULL,
    evidence      VARCHAR[],             -- links / rutas que justifican el nivel
    notes         VARCHAR
);

-- Hechos: eventos de aprendizaje (append-only, desde events/*.jsonl)
CREATE TABLE events (
    event_id      VARCHAR PRIMARY KEY,
    ts            TIMESTAMP NOT NULL,
    type          VARCHAR NOT NULL,      -- study_session | checkin | mock_interview | project_update | assessment | query
    domain        VARCHAR,
    skills        VARCHAR[],
    summary       VARCHAR,
    score         DOUBLE,                -- 0..10 para mocks/ejercicios
    duration_min  INTEGER,
    source_ref    VARCHAR                -- link a commit, nota, video...
);

-- Dimensión: proyectos (frontmatter de projects/*.md)
CREATE TABLE projects (
    project_id    VARCHAR PRIMARY KEY,
    name          VARCHAR,
    status        VARCHAR,               -- idea | en_curso | produccion | archivado
    repo_url      VARCHAR,
    domains       VARCHAR[],
    skills        VARCHAR[],
    path          VARCHAR
);

-- Dimensión: puestos analizados (frontmatter de jobs/*.md)
CREATE TABLE jobs (
    job_id        VARCHAR PRIMARY KEY,
    company       VARCHAR,
    title         VARCHAR,
    url           VARCHAR,
    captured_at   DATE,
    path          VARCHAR
);

-- Puente: requisitos de cada puesto
CREATE TABLE job_requirements (
    job_id        VARCHAR,
    skill_id      VARCHAR,
    importance    VARCHAR                -- must | nice
);

-- ------------------------------------------------------------
-- MARTS (vistas). Lo que el agente consulta para decidir.
-- ------------------------------------------------------------

-- ¿Qué me conviene estudiar? brecha de nivel x demanda del mercado
CREATE VIEW mart_skill_gaps AS
WITH demand AS (
    SELECT skill_id,
           count(DISTINCT job_id) AS jobs_requiring,
           count(DISTINCT job_id) FILTER (WHERE importance = 'must') AS jobs_must
    FROM job_requirements GROUP BY 1
),
total AS (SELECT greatest(count(*), 1) AS n_jobs FROM jobs),
practice AS (
    SELECT skill_id,
           max(ts) AS last_practiced,
           avg(score) FILTER (WHERE type = 'mock_interview') AS avg_mock_score
    FROM (SELECT unnest(skills) AS skill_id, ts, score, type FROM events)
    GROUP BY 1
)
SELECT k.skill_id, k.domain, k.name, k.level, k.target_level,
       k.target_level - k.level                            AS level_gap,
       coalesce(d.jobs_requiring, 0)                       AS jobs_requiring,
       coalesce(d.jobs_must, 0)                            AS jobs_must,
       round(coalesce(d.jobs_requiring, 0) / t.n_jobs, 2)  AS demand_ratio,
       coalesce(len(k.evidence), 0)                        AS evidence_count,
       p.last_practiced,
       round(p.avg_mock_score, 1)                          AS avg_mock_score,
       round(greatest(k.target_level - k.level, 0)
             * (1 + coalesce(d.jobs_requiring, 0) / t.n_jobs), 2) AS priority_score
FROM skills k
CROSS JOIN total t
LEFT JOIN demand d USING (skill_id)
LEFT JOIN practice p USING (skill_id)
ORDER BY priority_score DESC, jobs_requiring DESC;

-- Requisitos del mercado que ni siquiera tengo mapeados en skills.yaml
CREATE VIEW mart_unmapped_requirements AS
SELECT r.skill_id, count(DISTINCT r.job_id) AS jobs_requiring
FROM job_requirements r
LEFT JOIN skills s USING (skill_id)
WHERE s.skill_id IS NULL
GROUP BY 1 ORDER BY 2 DESC;

-- Actividad semanal
CREATE VIEW mart_weekly_activity AS
SELECT date_trunc('week', ts)        AS week,
       type,
       count(*)                       AS n_events,
       sum(coalesce(duration_min, 0)) AS minutes,
       round(avg(score), 1)           AS avg_score
FROM events
GROUP BY ALL
ORDER BY week DESC, type;
