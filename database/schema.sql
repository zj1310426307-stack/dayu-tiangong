-- 大禹·天工 Phase 2 水利数据库目标结构（权威迁移仍以 Alembic 为准）。
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE dataset_version (
    id serial PRIMARY KEY,
    version varchar(32) NOT NULL UNIQUE,
    name varchar(128) NOT NULL,
    description text,
    creator varchar(64) NOT NULL,
    created_time timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE river (
    id serial PRIMARY KEY,
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE RESTRICT,
    name varchar(128) NOT NULL,
    code varchar(64) NOT NULL,
    length double precision NOT NULL CHECK (length >= 0),
    level varchar(32) NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'planned')),
    description text,
    geometry geometry(LineString, 4490) NOT NULL,
    created_time timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_river_version_code UNIQUE (dataset_version_id, code)
);
CREATE INDEX ix_river_geometry_gist ON river USING gist (geometry);
CREATE INDEX ix_river_dataset_version_id ON river (dataset_version_id);

CREATE TABLE river_node (
    id serial PRIMARY KEY,
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE CASCADE,
    node_code varchar(64) NOT NULL,
    node_type varchar(24) NOT NULL CHECK (node_type IN ('start', 'end', 'confluence', 'bifurcation', 'gate_control')),
    longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    geometry geometry(Point, 4490) NOT NULL,
    CONSTRAINT uq_river_node_version_code UNIQUE (dataset_version_id, node_code)
);
CREATE INDEX ix_river_node_geometry_gist ON river_node USING gist (geometry);
CREATE INDEX ix_river_node_dataset_version_id ON river_node (dataset_version_id);

CREATE TABLE river_segment (
    id serial PRIMARY KEY,
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE CASCADE,
    river_id integer NOT NULL REFERENCES river(id) ON DELETE CASCADE,
    segment_code varchar(64) NOT NULL,
    upstream_node_id integer NOT NULL REFERENCES river_node(id) ON DELETE RESTRICT,
    downstream_node_id integer NOT NULL REFERENCES river_node(id) ON DELETE RESTRICT,
    length double precision NOT NULL CHECK (length >= 0),
    geometry geometry(LineString, 4490) NOT NULL,
    CONSTRAINT uq_river_segment_version_code UNIQUE (dataset_version_id, segment_code)
);
CREATE INDEX ix_river_segment_geometry_gist ON river_segment USING gist (geometry);
CREATE INDEX ix_river_segment_river_id ON river_segment (river_id);

CREATE TABLE river_connection (
    id serial PRIMARY KEY,
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE CASCADE,
    from_node_id integer NOT NULL REFERENCES river_node(id) ON DELETE CASCADE,
    to_node_id integer NOT NULL REFERENCES river_node(id) ON DELETE CASCADE,
    river_id integer NOT NULL REFERENCES river(id) ON DELETE CASCADE,
    CONSTRAINT uq_river_connection_edge UNIQUE (dataset_version_id, from_node_id, to_node_id, river_id)
);
CREATE INDEX ix_river_connection_river_id ON river_connection (river_id);
CREATE INDEX ix_river_connection_from_node_id ON river_connection (from_node_id);
CREATE INDEX ix_river_connection_to_node_id ON river_connection (to_node_id);

CREATE TABLE cross_section (
    id serial PRIMARY KEY,
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE CASCADE,
    river_id integer NOT NULL REFERENCES river(id) ON DELETE CASCADE,
    section_code varchar(64) NOT NULL,
    section_name varchar(128) NOT NULL,
    station double precision NOT NULL CHECK (station >= 0),
    points json NOT NULL,
    roughness double precision NOT NULL CHECK (roughness > 0),
    elevation_min double precision NOT NULL,
    survey_date date,
    geometry geometry(Point, 4490) NOT NULL,
    created_time timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_cross_section_version_code UNIQUE (dataset_version_id, section_code),
    CONSTRAINT uq_cross_section_version_river_station UNIQUE (dataset_version_id, river_id, station)
);
CREATE INDEX ix_cross_section_geometry_gist ON cross_section USING gist (geometry);
CREATE INDEX ix_cross_section_river_id ON cross_section (river_id);
CREATE INDEX ix_cross_section_dataset_version_id ON cross_section (dataset_version_id);

CREATE TABLE gate (
    id serial PRIMARY KEY,
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE CASCADE,
    name varchar(128) NOT NULL,
    gate_code varchar(64) NOT NULL,
    river_id integer NOT NULL REFERENCES river(id) ON DELETE RESTRICT,
    gate_type varchar(32) NOT NULL,
    opening_direction varchar(32) NOT NULL,
    control_mode varchar(32) NOT NULL,
    width double precision NOT NULL CHECK (width > 0),
    height double precision NOT NULL CHECK (height > 0),
    max_flow double precision NOT NULL CHECK (max_flow >= 0),
    bottom_elevation double precision NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'offline' CHECK (status IN ('online', 'offline', 'maintenance', 'fault')),
    geometry geometry(Point, 4490) NOT NULL,
    created_time timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_gate_version_code UNIQUE (dataset_version_id, gate_code)
);
CREATE INDEX ix_gate_geometry_gist ON gate USING gist (geometry);
CREATE INDEX ix_gate_river_id ON gate (river_id);
CREATE INDEX ix_gate_dataset_version_id ON gate (dataset_version_id);

CREATE TABLE pump (
    id serial PRIMARY KEY,
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE CASCADE,
    name varchar(128) NOT NULL,
    pump_code varchar(64) NOT NULL,
    river_id integer NOT NULL REFERENCES river(id) ON DELETE RESTRICT,
    design_flow double precision NOT NULL CHECK (design_flow >= 0),
    head double precision NOT NULL CHECK (head >= 0),
    power double precision NOT NULL CHECK (power >= 0),
    efficiency_curve json NOT NULL,
    control_mode varchar(32) NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'offline' CHECK (status IN ('online', 'offline', 'maintenance', 'fault')),
    geometry geometry(Point, 4490) NOT NULL,
    created_time timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_pump_version_code UNIQUE (dataset_version_id, pump_code)
);
CREATE INDEX ix_pump_geometry_gist ON pump USING gist (geometry);
CREATE INDEX ix_pump_river_id ON pump (river_id);
CREATE INDEX ix_pump_dataset_version_id ON pump (dataset_version_id);

CREATE TABLE model_parameter (
    id serial PRIMARY KEY,
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE CASCADE,
    parameter_type varchar(64) NOT NULL,
    parameter_name varchar(128) NOT NULL,
    value double precision NOT NULL,
    unit varchar(32) NOT NULL,
    description text,
    CONSTRAINT uq_model_parameter_version_name UNIQUE (dataset_version_id, parameter_type, parameter_name)
);

CREATE TABLE boundary_condition (
    id serial PRIMARY KEY,
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE CASCADE,
    name varchar(128) NOT NULL,
    boundary_type varchar(64) NOT NULL,
    target_node_id integer REFERENCES river_node(id) ON DELETE SET NULL,
    values json NOT NULL,
    unit varchar(32) NOT NULL,
    description text,
    CONSTRAINT uq_boundary_condition_version_name UNIQUE (dataset_version_id, name)
);

CREATE TABLE simulation_case (
    id serial PRIMARY KEY,
    name varchar(128) NOT NULL UNIQUE,
    description text,
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE RESTRICT,
    boundary_condition_id integer NOT NULL REFERENCES boundary_condition(id) ON DELETE RESTRICT,
    created_time timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE simulation_task (
    id serial PRIMARY KEY,
    case_id integer NOT NULL REFERENCES simulation_case(id) ON DELETE RESTRICT,
    status varchar(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'queued', 'running', 'cancel_requested',
                          'cancelled', 'success', 'failed')),
    progress integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    config json NOT NULL,
    input_schema_version varchar(48),
    input_snapshot json,
    input_snapshot_hash varchar(64),
    engine_version varchar(64),
    engine_commit varchar(64),
    queue_job_id varchar(128),
    worker_id varchar(128),
    queued_time timestamptz,
    heartbeat_time timestamptz,
    cancel_requested boolean NOT NULL DEFAULT false,
    retry_count integer NOT NULL DEFAULT 0,
    retry_reason text,
    current_simulation_time double precision,
    current_cfl double precision,
    diagnostics json,
    result_path text,
    error_message text,
    created_time timestamptz NOT NULL DEFAULT now(),
    start_time timestamptz,
    end_time timestamptz
);
CREATE INDEX ix_simulation_task_case_id ON simulation_task (case_id);
CREATE INDEX ix_simulation_task_status ON simulation_task (status);
CREATE INDEX ix_simulation_task_snapshot_hash ON simulation_task (input_snapshot_hash);

CREATE TABLE simulation_result (
    id serial PRIMARY KEY,
    task_id integer NOT NULL REFERENCES simulation_task(id) ON DELETE CASCADE,
    section_id integer REFERENCES cross_section(id) ON DELETE SET NULL,
    river_id integer REFERENCES river(id) ON DELETE SET NULL,
    section_code varchar(64) NOT NULL,
    station double precision NOT NULL,
    time_seconds double precision NOT NULL,
    water_level double precision NOT NULL,
    flow double precision NOT NULL,
    velocity double precision NOT NULL,
    CONSTRAINT uq_simulation_result_task_section_time
        UNIQUE (task_id, section_code, time_seconds)
);
CREATE INDEX ix_simulation_result_task_id ON simulation_result (task_id);
CREATE INDEX ix_simulation_result_section_id ON simulation_result (section_id);
CREATE INDEX ix_simulation_result_river_id ON simulation_result (river_id);

-- Phase 4 增量字段与表；迁移 0004/0005 是运行时权威来源。
ALTER TABLE gate
    ADD COLUMN river_segment_id integer REFERENCES river_segment(id) ON DELETE SET NULL,
    ADD COLUMN station double precision,
    ADD COLUMN upstream_node_id integer REFERENCES river_node(id) ON DELETE SET NULL,
    ADD COLUMN downstream_node_id integer REFERENCES river_node(id) ON DELETE SET NULL,
    ADD COLUMN crest_elevation double precision,
    ADD COLUMN discharge_coefficient double precision,
    ADD COLUMN minimum_opening double precision,
    ADD COLUMN maximum_opening double precision,
    ADD COLUMN opening_rate_limit double precision,
    ADD COLUMN minimum_hold_seconds double precision,
    ADD COLUMN allow_reverse_flow boolean NOT NULL DEFAULT false;

ALTER TABLE pump
    ADD COLUMN head_curve json,
    ADD COLUMN intake_node_id integer REFERENCES river_node(id) ON DELETE SET NULL,
    ADD COLUMN outlet_node_id integer REFERENCES river_node(id) ON DELETE SET NULL,
    ADD COLUMN transfer_type varchar(24),
    ADD COLUMN unit_count integer,
    ADD COLUMN minimum_running_units integer,
    ADD COLUMN maximum_running_units integer,
    ADD COLUMN minimum_run_seconds double precision,
    ADD COLUMN minimum_stop_seconds double precision,
    ADD COLUMN maximum_starts_per_run integer,
    ADD COLUMN minimum_operating_head double precision,
    ADD COLUMN maximum_operating_head double precision,
    ADD COLUMN reverse_flow_protection boolean NOT NULL DEFAULT true;

CREATE TABLE simulation_case_boundary (
    case_id integer NOT NULL REFERENCES simulation_case(id) ON DELETE CASCADE,
    boundary_condition_id integer NOT NULL REFERENCES boundary_condition(id) ON DELETE RESTRICT,
    role varchar(32) NOT NULL,
    created_time timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, boundary_condition_id)
);

CREATE TABLE dispatch_plan (
    id serial PRIMARY KEY,
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE RESTRICT,
    simulation_case_id integer NOT NULL REFERENCES simulation_case(id) ON DELETE RESTRICT,
    name varchar(128) NOT NULL,
    version integer NOT NULL DEFAULT 1,
    status varchar(16) NOT NULL DEFAULT 'draft',
    description text,
    duration_seconds double precision NOT NULL,
    evaluation_config json NOT NULL,
    storage_level varchar(16) NOT NULL DEFAULT 'key_sections',
    created_by varchar(64) NOT NULL,
    created_time timestamptz NOT NULL DEFAULT now(),
    updated_time timestamptz NOT NULL DEFAULT now(),
    frozen_time timestamptz,
    frozen_snapshot json,
    frozen_snapshot_hash varchar(64),
    UNIQUE (name, version)
);
CREATE INDEX ix_dispatch_plan_dataset_version_id ON dispatch_plan (dataset_version_id);
CREATE INDEX ix_dispatch_plan_status ON dispatch_plan (status);

CREATE TABLE dispatch_action (
    id serial PRIMARY KEY,
    plan_id integer NOT NULL REFERENCES dispatch_plan(id) ON DELETE CASCADE,
    sequence integer NOT NULL,
    time_seconds double precision NOT NULL,
    structure_type varchar(16) NOT NULL,
    gate_id integer REFERENCES gate(id) ON DELETE RESTRICT,
    pump_id integer REFERENCES pump(id) ON DELETE RESTRICT,
    command_type varchar(32) NOT NULL,
    target_value double precision NOT NULL,
    interpolation varchar(16) NOT NULL DEFAULT 'step',
    priority integer NOT NULL DEFAULT 0,
    note text,
    CHECK ((gate_id IS NOT NULL) <> (pump_id IS NOT NULL))
);

CREATE TABLE dispatch_rule (
    id serial PRIMARY KEY,
    plan_id integer NOT NULL REFERENCES dispatch_plan(id) ON DELETE CASCADE,
    name varchar(128) NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    observation_type varchar(32) NOT NULL,
    observation_object_id integer,
    operator varchar(4) NOT NULL,
    threshold double precision NOT NULL,
    hysteresis double precision NOT NULL DEFAULT 0,
    minimum_hold_seconds double precision NOT NULL DEFAULT 0,
    cooldown_seconds double precision NOT NULL DEFAULT 0,
    action_template json NOT NULL,
    priority integer NOT NULL DEFAULT 0
);

CREATE TABLE dispatch_run (
    id serial PRIMARY KEY,
    plan_id integer NOT NULL REFERENCES dispatch_plan(id) ON DELETE RESTRICT,
    baseline_task_id integer REFERENCES simulation_task(id) ON DELETE SET NULL,
    controlled_task_id integer REFERENCES simulation_task(id) ON DELETE SET NULL,
    status varchar(24) NOT NULL DEFAULT 'pending',
    progress integer NOT NULL DEFAULT 0,
    metrics json,
    queue_job_id varchar(128),
    error_message text,
    created_time timestamptz NOT NULL DEFAULT now(),
    start_time timestamptz,
    end_time timestamptz
);

CREATE TABLE dispatch_event (
    id serial PRIMARY KEY,
    run_id integer NOT NULL REFERENCES dispatch_run(id) ON DELETE CASCADE,
    time_seconds double precision NOT NULL,
    source_type varchar(16) NOT NULL,
    source_id integer,
    structure_type varchar(16) NOT NULL,
    structure_id integer NOT NULL,
    requested_command json NOT NULL,
    applied_command json,
    outcome varchar(16) NOT NULL,
    reason text,
    created_time timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE structure_result (
    id serial PRIMARY KEY,
    task_id integer NOT NULL REFERENCES simulation_task(id) ON DELETE CASCADE,
    dispatch_run_id integer REFERENCES dispatch_run(id) ON DELETE CASCADE,
    time_seconds double precision NOT NULL,
    structure_type varchar(16) NOT NULL,
    structure_id integer NOT NULL,
    requested_value double precision,
    actual_value double precision,
    flow double precision NOT NULL,
    upstream_level double precision,
    downstream_level double precision,
    head_difference double precision,
    transfer_type varchar(24),
    power_kw double precision,
    energy_kwh double precision,
    regime varchar(32),
    constraint_flags json NOT NULL,
    UNIQUE (task_id, time_seconds, structure_type, structure_id)
);

CREATE TABLE junction_result (
    id serial PRIMARY KEY,
    task_id integer NOT NULL REFERENCES simulation_task(id) ON DELETE CASCADE,
    node_id integer NOT NULL REFERENCES river_node(id) ON DELETE RESTRICT,
    time_seconds double precision NOT NULL,
    water_level double precision NOT NULL,
    inflow double precision NOT NULL,
    outflow double precision NOT NULL,
    source_sink double precision NOT NULL,
    balance_residual double precision NOT NULL,
    UNIQUE (task_id, node_id, time_seconds)
);

CREATE TABLE optimization_task (
    id serial PRIMARY KEY,
    name varchar(128) NOT NULL,
    algorithm varchar(32) NOT NULL DEFAULT 'pso',
    status varchar(16) NOT NULL DEFAULT 'pending',
    dataset_version_id integer NOT NULL REFERENCES dataset_version(id) ON DELETE RESTRICT,
    simulation_case_id integer NOT NULL REFERENCES simulation_case(id) ON DELETE RESTRICT,
    objective_config json NOT NULL,
    algorithm_config json NOT NULL,
    input_snapshot json NOT NULL,
    input_snapshot_hash varchar(64) NOT NULL,
    algorithm_version varchar(64) NOT NULL,
    progress integer NOT NULL DEFAULT 0,
    current_generation integer NOT NULL DEFAULT 0,
    best_score double precision,
    queue_job_id varchar(128), worker_id varchar(128),
    cancel_requested boolean NOT NULL DEFAULT false,
    converged boolean NOT NULL DEFAULT false,
    error_message text, created_time timestamptz NOT NULL DEFAULT now(),
    start_time timestamptz, end_time timestamptz
);

CREATE TABLE optimization_candidate (
    id serial PRIMARY KEY,
    task_id integer NOT NULL REFERENCES optimization_task(id) ON DELETE CASCADE,
    generation integer NOT NULL, candidate_index integer NOT NULL,
    dispatch_plan json NOT NULL, score double precision, objective_values json, metrics json,
    valid boolean NOT NULL DEFAULT true, constraint_reasons json NOT NULL,
    simulation_task_id integer REFERENCES simulation_task(id) ON DELETE SET NULL,
    created_time timestamptz NOT NULL DEFAULT now(),
    UNIQUE (task_id, generation, candidate_index)
);

CREATE TABLE optimization_result (
    candidate_id integer PRIMARY KEY REFERENCES optimization_candidate(id) ON DELETE CASCADE,
    task_id integer NOT NULL REFERENCES optimization_task(id) ON DELETE CASCADE,
    pareto_level integer NOT NULL, rank integer NOT NULL,
    recommendation_status varchar(16) NOT NULL, explanation json NOT NULL
);
