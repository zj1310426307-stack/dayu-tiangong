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
    geometry geometry(LineString, 4326) NOT NULL,
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
    geometry geometry(Point, 4326) NOT NULL,
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
    geometry geometry(LineString, 4326) NOT NULL,
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
    geometry geometry(Point, 4326) NOT NULL,
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
    geometry geometry(Point, 4326) NOT NULL,
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
    geometry geometry(Point, 4326) NOT NULL,
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
