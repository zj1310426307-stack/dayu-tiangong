/* 本文件由 npm run openapi:update 自动生成，请勿手工修改。 */

export interface AlgorithmConfig {
  "particle_count"?: number;
  "max_iterations"?: number;
  "inertia"?: number;
  "cognitive"?: number;
  "social"?: number;
  "tolerance"?: number;
  "patience"?: number;
  "seed"?: number;
  "duration_seconds"?: number;
  "time_step_seconds"?: number;
  "output_interval_seconds"?: number;
  "constraints"?: ConstraintConfig;
}

export interface app__dispatch__schemas__ValidationReport {
  "plan_id": number;
  "valid": boolean;
  "errors": Array<string>;
  "warnings": Array<string>;
}

export interface app__validation__schemas__ValidationReport {
  "dataset_version_id": number;
  "checked_time": string;
  "summary": ValidationSummary;
  "items": Array<ValidationItem>;
}

export interface Body_import_csv_api_v1_import_csv_post {
  "resource": "rivers" | "cross_sections" | "gates" | "pumps";
  "dataset_version_id": number;
  "file": string;
}

export interface Body_import_excel_api_v1_import_excel_post {
  "resource": "rivers" | "cross_sections" | "gates" | "pumps";
  "dataset_version_id": number;
  "file": string;
}

export interface Body_import_geojson_api_v1_import_geojson_post {
  "resource": "rivers" | "cross_sections" | "gates" | "pumps";
  "dataset_version_id": number;
  "file": string;
}

export interface BoundaryConditionCreate {
  "dataset_version_id": number;
  "name": string;
  "boundary_type": string;
  "target_node_id"?: number | null;
  "values": Record<string, unknown>;
  "unit": string;
  "description"?: string | null;
}

export interface BoundaryConditionRecord {
  "dataset_version_id": number;
  "name": string;
  "boundary_type": string;
  "target_node_id"?: number | null;
  "values": Record<string, unknown>;
  "unit": string;
  "description"?: string | null;
  "id": number;
}

export interface BoundaryConditionUpdate {
  "name"?: string | null;
  "boundary_type"?: string | null;
  "target_node_id"?: number | null;
  "values"?: Record<string, unknown> | null;
  "unit"?: string | null;
  "description"?: string | null;
}

export interface ConstraintConfig {
  "maximum_actions_per_asset"?: number;
  "maximum_pump_starts"?: number;
  "invalid_penalty"?: number;
  "hydraulic_limits"?: HydraulicLimits;
}

export interface CrossSectionCreate {
  "dataset_version_id": number;
  "river_id": number;
  "section_code": string;
  "section_name": string;
  "station": number;
  "points": Record<string, Array<Array<number>>>;
  "roughness": number;
  "elevation_min": number;
  "survey_date"?: string | null;
  "geometry": Record<string, unknown>;
}

export interface CrossSectionListResponse {
  "items": Array<CrossSectionRecord>;
  "total": number;
  "limit": number;
  "offset": number;
}

export interface CrossSectionRecord {
  "dataset_version_id": number;
  "river_id": number;
  "section_code": string;
  "section_name": string;
  "station": number;
  "points": Record<string, Array<Array<number>>>;
  "roughness": number;
  "elevation_min": number;
  "survey_date"?: string | null;
  "geometry": Record<string, unknown>;
  "id": number;
  "created_time": string;
}

export interface CrossSectionUpdate {
  "river_id"?: number | null;
  "section_code"?: string | null;
  "section_name"?: string | null;
  "station"?: number | null;
  "points"?: Record<string, Array<Array<number>>> | null;
  "roughness"?: number | null;
  "elevation_min"?: number | null;
  "survey_date"?: string | null;
  "geometry"?: Record<string, unknown> | null;
}

export interface DatasetVersionCreate {
  "version": string;
  "name": string;
  "description"?: string | null;
  "creator": string;
}

export interface DatasetVersionRecord {
  "version": string;
  "name": string;
  "description"?: string | null;
  "creator": string;
  "id": number;
  "created_time": string;
}

export interface DatasetVersionUpdate {
  "name"?: string | null;
  "description"?: string | null;
}

export interface DispatchActionCreate {
  "sequence": number;
  "time_seconds": number;
  "structure_type": "gate" | "pump";
  "gate_id"?: number | null;
  "pump_id"?: number | null;
  "command_type": "gate_opening_m" | "gate_opening_ratio" | "pump_enabled" | "pump_unit_count" | "pump_target_flow";
  "target_value": number;
  "interpolation"?: "step" | "linear";
  "priority"?: number;
  "note"?: string | null;
}

export interface DispatchActionRecord {
  "sequence": number;
  "time_seconds": number;
  "structure_type": "gate" | "pump";
  "gate_id"?: number | null;
  "pump_id"?: number | null;
  "command_type": "gate_opening_m" | "gate_opening_ratio" | "pump_enabled" | "pump_unit_count" | "pump_target_flow";
  "target_value": number;
  "interpolation"?: "step" | "linear";
  "priority"?: number;
  "note"?: string | null;
  "id": number;
  "plan_id": number;
}

export interface DispatchActionUpdate {
  "sequence"?: number | null;
  "time_seconds"?: number | null;
  "command_type"?: "gate_opening_m" | "gate_opening_ratio" | "pump_enabled" | "pump_unit_count" | "pump_target_flow" | null;
  "target_value"?: number | null;
  "interpolation"?: "step" | "linear" | null;
  "priority"?: number | null;
  "note"?: string | null;
}

export interface DispatchComparison {
  "run_id": number;
  "status": "pending" | "queued" | "running" | "cancel_requested" | "cancelled" | "success" | "failed";
  "baseline_task_id": number | null;
  "controlled_task_id": number | null;
  "section_code": string | null;
  "time": Array<number>;
  "baseline_water_level": Array<number>;
  "controlled_water_level": Array<number>;
  "difference": Array<number>;
  "metrics": Record<string, unknown>;
  "diagnostics": Record<string, unknown>;
}

export interface DispatchPlanCreate {
  "dataset_version_id": number;
  "simulation_case_id": number;
  "name": string;
  "description"?: string | null;
  "duration_seconds": number;
  "evaluation_config"?: Record<string, unknown>;
  "storage_level"?: "summary" | "key_sections" | "full";
  "created_by"?: string;
}

export interface DispatchPlanRecord {
  "id": number;
  "dataset_version_id": number;
  "simulation_case_id": number;
  "name": string;
  "version": number;
  "status": "draft" | "validated" | "frozen" | "archived";
  "description": string | null;
  "duration_seconds": number;
  "evaluation_config": Record<string, unknown>;
  "storage_level": string;
  "created_by": string;
  "created_time": string;
  "updated_time": string;
  "frozen_time": string | null;
  "frozen_snapshot_hash": string | null;
  "action_count"?: number;
  "rule_count"?: number;
}

export interface DispatchPlanUpdate {
  "name"?: string | null;
  "description"?: string | null;
  "duration_seconds"?: number | null;
  "evaluation_config"?: Record<string, unknown> | null;
  "storage_level"?: "summary" | "key_sections" | "full" | null;
  "status"?: "archived" | null;
}

export interface DispatchRuleCreate {
  "name": string;
  "enabled"?: boolean;
  "observation_type": "elapsed_time" | "node_water_level" | "section_water_level" | "gate_head_difference" | "pump_intake_level";
  "observation_object_id"?: number | null;
  "operator": ">" | ">=" | "<" | "<=";
  "threshold": number;
  "hysteresis"?: number;
  "minimum_hold_seconds"?: number;
  "cooldown_seconds"?: number;
  "action_template": Record<string, unknown>;
  "priority"?: number;
}

export interface DispatchRuleRecord {
  "name": string;
  "enabled"?: boolean;
  "observation_type": "elapsed_time" | "node_water_level" | "section_water_level" | "gate_head_difference" | "pump_intake_level";
  "observation_object_id"?: number | null;
  "operator": ">" | ">=" | "<" | "<=";
  "threshold": number;
  "hysteresis"?: number;
  "minimum_hold_seconds"?: number;
  "cooldown_seconds"?: number;
  "action_template": Record<string, unknown>;
  "priority"?: number;
  "id": number;
  "plan_id": number;
}

export interface DispatchRuleUpdate {
  "name"?: string | null;
  "enabled"?: boolean | null;
  "threshold"?: number | null;
  "hysteresis"?: number | null;
  "minimum_hold_seconds"?: number | null;
  "cooldown_seconds"?: number | null;
  "action_template"?: Record<string, unknown> | null;
  "priority"?: number | null;
}

export interface DispatchRunRecord {
  "id": number;
  "plan_id": number;
  "baseline_task_id": number | null;
  "controlled_task_id": number | null;
  "status": "pending" | "queued" | "running" | "cancel_requested" | "cancelled" | "success" | "failed";
  "progress": number;
  "metrics": Record<string, unknown> | null;
  "queue_job_id": string | null;
  "error_message": string | null;
  "created_time": string;
  "start_time": string | null;
  "end_time": string | null;
}

export interface GateCreate {
  "dataset_version_id": number;
  "name": string;
  "river_id": number;
  "control_mode": string;
  "status"?: "online" | "offline" | "maintenance" | "fault";
  "geometry": Record<string, unknown>;
  "gate_code": string;
  "gate_type": string;
  "opening_direction": string;
  "width": number;
  "height": number;
  "max_flow": number;
  "bottom_elevation": number;
  "river_segment_id"?: number | null;
  "station"?: number | null;
  "upstream_node_id"?: number | null;
  "downstream_node_id"?: number | null;
  "crest_elevation"?: number | null;
  "discharge_coefficient"?: number | null;
  "minimum_opening"?: number | null;
  "maximum_opening"?: number | null;
  "opening_rate_limit"?: number | null;
  "minimum_hold_seconds"?: number | null;
  "allow_reverse_flow"?: boolean;
}

export interface GateListResponse {
  "items": Array<GateRecord>;
  "total": number;
  "limit": number;
  "offset": number;
}

export interface GateRecord {
  "dataset_version_id": number;
  "name": string;
  "river_id": number;
  "control_mode": string;
  "status"?: "online" | "offline" | "maintenance" | "fault";
  "geometry": Record<string, unknown>;
  "gate_code": string;
  "gate_type": string;
  "opening_direction": string;
  "width": number;
  "height": number;
  "max_flow": number;
  "bottom_elevation": number;
  "river_segment_id"?: number | null;
  "station"?: number | null;
  "upstream_node_id"?: number | null;
  "downstream_node_id"?: number | null;
  "crest_elevation"?: number | null;
  "discharge_coefficient"?: number | null;
  "minimum_opening"?: number | null;
  "maximum_opening"?: number | null;
  "opening_rate_limit"?: number | null;
  "minimum_hold_seconds"?: number | null;
  "allow_reverse_flow"?: boolean;
  "id": number;
  "created_time": string;
}

export interface GateUpdate {
  "name"?: string | null;
  "river_id"?: number | null;
  "gate_code"?: string | null;
  "gate_type"?: string | null;
  "opening_direction"?: string | null;
  "control_mode"?: string | null;
  "width"?: number | null;
  "height"?: number | null;
  "max_flow"?: number | null;
  "bottom_elevation"?: number | null;
  "river_segment_id"?: number | null;
  "station"?: number | null;
  "upstream_node_id"?: number | null;
  "downstream_node_id"?: number | null;
  "crest_elevation"?: number | null;
  "discharge_coefficient"?: number | null;
  "minimum_opening"?: number | null;
  "maximum_opening"?: number | null;
  "opening_rate_limit"?: number | null;
  "minimum_hold_seconds"?: number | null;
  "allow_reverse_flow"?: boolean | null;
  "status"?: "online" | "offline" | "maintenance" | "fault" | null;
  "geometry"?: Record<string, unknown> | null;
}

export interface GeoJSONFeature {
  "type"?: "Feature";
  "id": number;
  "geometry": Record<string, unknown>;
  "properties": Record<string, unknown>;
}

export interface GeoJSONFeatureCollection {
  "type"?: "FeatureCollection";
  "features": Array<GeoJSONFeature>;
  "meta": PaginationMeta;
}

export interface GISHealthResponse {
  "status": "healthy";
  "database": string;
  "postgis_version": string;
  "srid"?: 4490;
}

export interface GISStatisticsResponse {
  "rivers": number;
  "gates": number;
  "pumps": number;
  "cross_sections": number;
  "demo_data"?: true;
  "source"?: "PostGIS / DEMO DATA";
}

export interface HealthResponse {
  "status": "healthy";
  "service": string;
  "version": string;
}

export interface HTTPValidationError {
  "detail"?: Array<ValidationError>;
}

export interface HydraulicLimits {
  "maximum_water_level"?: number | null;
  "maximum_flow"?: number | null;
  "maximum_pump_power_kw"?: number | null;
}

export interface ImportIssue {
  "row": number;
  "message": string;
}

export interface ImportResponse {
  "status": "success" | "failed";
  "resource": string;
  "imported_count": number;
  "stored_filename": string;
  "errors": Array<ImportIssue>;
  "warnings": Array<ImportIssue>;
}

export interface ModelInputSnapshot {
  "schema_version"?: string;
  "generated_time": string;
  "simulation_case": SimulationCaseRecord;
  "dataset_version": DatasetVersionRecord;
  "rivers": Array<Record<string, unknown>>;
  "nodes": Array<Record<string, unknown>>;
  "segments": Array<Record<string, unknown>>;
  "connections": Array<Record<string, unknown>>;
  "cross_sections": Array<Record<string, unknown>>;
  "gates": Array<Record<string, unknown>>;
  "pumps": Array<Record<string, unknown>>;
  "parameters": Array<ModelParameterRecord>;
  "boundary_conditions": Array<BoundaryConditionRecord>;
}

export interface ModelParameterCreate {
  "dataset_version_id": number;
  "parameter_type": string;
  "parameter_name": string;
  "value": number;
  "unit": string;
  "description"?: string | null;
}

export interface ModelParameterRecord {
  "dataset_version_id": number;
  "parameter_type": string;
  "parameter_name": string;
  "value": number;
  "unit": string;
  "description"?: string | null;
  "id": number;
}

export interface ModelParameterUpdate {
  "value"?: number | null;
  "unit"?: string | null;
  "description"?: string | null;
}

export interface ObjectiveConfig {
  "version"?: "dayu.objectives.v1";
  "weights"?: ObjectiveWeights;
  "normalization"?: ObjectiveNormalization;
  "warning_level"?: number | null;
  "guarantee_level"?: number | null;
}

export interface ObjectiveNormalization {
  "maximum_water_level"?: number;
  "warning_duration"?: number;
  "guarantee_duration"?: number;
  "pump_energy_kwh"?: number;
  "pump_runtime_seconds"?: number;
  "pump_start_count"?: number;
  "gate_action_count"?: number;
  "gate_cumulative_opening_change"?: number;
  "pump_stop_count"?: number;
}

export interface ObjectiveWeights {
  "flood_risk"?: number;
  "energy_cost"?: number;
  "operation_cost"?: number;
}

export interface OptimizationCandidateRecord {
  "id": number;
  "task_id": number;
  "generation": number;
  "candidate_index": number;
  "dispatch_plan": Record<string, unknown>;
  "score": number | null;
  "objective_values": Record<string, unknown> | null;
  "metrics": Record<string, unknown> | null;
  "valid": boolean;
  "constraint_reasons": Array<string>;
  "simulation_task_id": number | null;
  "created_time": string;
}

export interface OptimizationExplanation {
  "task_id": number;
  "candidate_id": number | null;
  "explanation_type"?: "deterministic_template";
  "summary": string;
  "factors": Array<string>;
  "limitations": Array<string>;
}

export interface OptimizationTaskCreate {
  "name": string;
  "algorithm"?: "pso";
  "dataset_version_id": number;
  "simulation_case_id": number;
  "objective_config"?: ObjectiveConfig;
  "algorithm_config"?: AlgorithmConfig;
}

export interface OptimizationTaskRecord {
  "id": number;
  "name": string;
  "algorithm": string;
  "status": "pending" | "running" | "success" | "failed" | "cancelled";
  "dataset_version_id": number;
  "simulation_case_id": number;
  "objective_config": Record<string, unknown>;
  "algorithm_config": Record<string, unknown>;
  "input_snapshot_hash": string;
  "algorithm_version": string;
  "progress": number;
  "current_generation": number;
  "best_score": number | null;
  "queue_job_id": string | null;
  "worker_id": string | null;
  "cancel_requested": boolean;
  "converged": boolean;
  "error_message": string | null;
  "created_time": string;
  "start_time": string | null;
  "end_time": string | null;
  "candidate_count"?: number;
  "pareto_count"?: number;
  "recommended_candidate_id"?: number | null;
}

export interface Page {
  "items": Array<unknown>;
  "total": number;
  "limit": number;
  "offset": number;
}

export interface PaginationMeta {
  "total": number;
  "limit": number;
  "offset": number;
  "bbox"?: Array<number> | null;
  "demo_data"?: true;
  "crs"?: "EPSG:4490";
}

export interface ParetoCandidateRecord {
  "id": number;
  "task_id": number;
  "generation": number;
  "candidate_index": number;
  "dispatch_plan": Record<string, unknown>;
  "score": number | null;
  "objective_values": Record<string, unknown> | null;
  "metrics": Record<string, unknown> | null;
  "valid": boolean;
  "constraint_reasons": Array<string>;
  "simulation_task_id": number | null;
  "created_time": string;
  "pareto_level": number;
  "rank": number;
  "recommendation_status": string;
  "explanation": Record<string, unknown>;
}

export interface PumpCreate {
  "dataset_version_id": number;
  "name": string;
  "river_id": number;
  "control_mode": string;
  "status"?: "online" | "offline" | "maintenance" | "fault";
  "geometry": Record<string, unknown>;
  "pump_code": string;
  "design_flow": number;
  "head": number;
  "power": number;
  "efficiency_curve": Record<string, Array<Array<number>>>;
  "head_curve"?: Record<string, Array<Array<number>>> | null;
  "intake_node_id"?: number | null;
  "outlet_node_id"?: number | null;
  "transfer_type"?: "internal_transfer" | "external_outflow" | "external_inflow" | null;
  "unit_count"?: number | null;
  "minimum_running_units"?: number | null;
  "maximum_running_units"?: number | null;
  "minimum_run_seconds"?: number | null;
  "minimum_stop_seconds"?: number | null;
  "maximum_starts_per_run"?: number | null;
  "minimum_operating_head"?: number | null;
  "maximum_operating_head"?: number | null;
  "reverse_flow_protection"?: boolean;
}

export interface PumpListResponse {
  "items": Array<PumpRecord>;
  "total": number;
  "limit": number;
  "offset": number;
}

export interface PumpRecord {
  "dataset_version_id": number;
  "name": string;
  "river_id": number;
  "control_mode": string;
  "status"?: "online" | "offline" | "maintenance" | "fault";
  "geometry": Record<string, unknown>;
  "pump_code": string;
  "design_flow": number;
  "head": number;
  "power": number;
  "efficiency_curve": Record<string, Array<Array<number>>>;
  "head_curve"?: Record<string, Array<Array<number>>> | null;
  "intake_node_id"?: number | null;
  "outlet_node_id"?: number | null;
  "transfer_type"?: "internal_transfer" | "external_outflow" | "external_inflow" | null;
  "unit_count"?: number | null;
  "minimum_running_units"?: number | null;
  "maximum_running_units"?: number | null;
  "minimum_run_seconds"?: number | null;
  "minimum_stop_seconds"?: number | null;
  "maximum_starts_per_run"?: number | null;
  "minimum_operating_head"?: number | null;
  "maximum_operating_head"?: number | null;
  "reverse_flow_protection"?: boolean;
  "id": number;
  "created_time": string;
}

export interface PumpUpdate {
  "name"?: string | null;
  "river_id"?: number | null;
  "pump_code"?: string | null;
  "design_flow"?: number | null;
  "head"?: number | null;
  "power"?: number | null;
  "efficiency_curve"?: Record<string, Array<Array<number>>> | null;
  "head_curve"?: Record<string, Array<Array<number>>> | null;
  "intake_node_id"?: number | null;
  "outlet_node_id"?: number | null;
  "transfer_type"?: "internal_transfer" | "external_outflow" | "external_inflow" | null;
  "unit_count"?: number | null;
  "minimum_running_units"?: number | null;
  "maximum_running_units"?: number | null;
  "minimum_run_seconds"?: number | null;
  "minimum_stop_seconds"?: number | null;
  "maximum_starts_per_run"?: number | null;
  "minimum_operating_head"?: number | null;
  "maximum_operating_head"?: number | null;
  "reverse_flow_protection"?: boolean | null;
  "control_mode"?: string | null;
  "status"?: "online" | "offline" | "maintenance" | "fault" | null;
  "geometry"?: Record<string, unknown> | null;
}

export interface RecommendationResponse {
  "task_id": number;
  "candidate": ParetoCandidateRecord | null;
  "execution_authorized"?: false;
  "notice"?: string;
}

export interface ResultSectionOption {
  "section_id": number | null;
  "section_code": string;
  "river_id": number | null;
  "station": number;
}

export interface RiverConnectionRecord {
  "id": number;
  "dataset_version_id": number;
  "from_node_id": number;
  "to_node_id": number;
  "river_id": number;
}

export interface RiverCreate {
  "dataset_version_id": number;
  "name": string;
  "code": string;
  "length": number;
  "level": string;
  "status"?: "active" | "inactive" | "planned";
  "description"?: string | null;
  "geometry": Record<string, unknown>;
}

export interface RiverListResponse {
  "items": Array<RiverRecord>;
  "total": number;
  "limit": number;
  "offset": number;
}

export interface RiverNodeRecord {
  "id": number;
  "dataset_version_id": number;
  "node_code": string;
  "node_type": string;
  "longitude": number;
  "latitude": number;
  "geometry": Record<string, unknown>;
}

export interface RiverRecord {
  "dataset_version_id": number;
  "name": string;
  "code": string;
  "length": number;
  "level": string;
  "status"?: "active" | "inactive" | "planned";
  "description"?: string | null;
  "geometry": Record<string, unknown>;
  "id": number;
  "created_time": string;
}

export interface RiverSegmentRecord {
  "id": number;
  "dataset_version_id": number;
  "river_id": number;
  "segment_code": string;
  "upstream_node_id": number;
  "downstream_node_id": number;
  "length": number;
  "geometry": Record<string, unknown>;
}

export interface RiverUpdate {
  "name"?: string | null;
  "code"?: string | null;
  "length"?: number | null;
  "level"?: string | null;
  "status"?: "active" | "inactive" | "planned" | null;
  "description"?: string | null;
  "geometry"?: Record<string, unknown> | null;
}

export interface SimulationCaseCreate {
  "name": string;
  "description"?: string | null;
  "dataset_version_id": number;
  "boundary_condition_id": number;
  "boundary_condition_ids"?: Array<number>;
}

export interface SimulationCaseRecord {
  "name": string;
  "description"?: string | null;
  "dataset_version_id": number;
  "boundary_condition_id": number;
  "boundary_condition_ids"?: Array<number>;
  "id": number;
  "created_time": string;
}

export interface SimulationCaseUpdate {
  "name"?: string | null;
  "description"?: string | null;
  "boundary_condition_id"?: number | null;
  "boundary_condition_ids"?: Array<number> | null;
}

export interface SimulationResultResponse {
  "task_id": number;
  "status": "pending" | "queued" | "running" | "cancel_requested" | "cancelled" | "success" | "failed";
  "section_id": number | null;
  "section_code": string;
  "river_id": number | null;
  "station": number;
  "time": Array<number>;
  "water_level": Array<number>;
  "flow": Array<number>;
  "velocity": Array<number>;
  "available_sections": Array<ResultSectionOption>;
  "diagnostics": Record<string, unknown> | null;
}

export interface SimulationTaskCreate {
  "case_id": number;
  "duration_seconds"?: number | null;
  "time_step_seconds"?: number | null;
  "output_interval_seconds"?: number | null;
  "cfl_number"?: number | null;
  "initial_water_level"?: number | null;
  "initial_flow"?: number | null;
  "minimum_depth"?: number | null;
  "input_schema_version"?: "dayu.model-input.v1" | "dayu.model-input.v2";
  "allow_fallback_boundary"?: boolean;
  "section_geometry"?: "rectangular" | "tabulated";
  "storage_level"?: "summary" | "key_sections" | "full";
}

export interface SimulationTaskRecord {
  "id": number;
  "case_id": number;
  "status": "pending" | "queued" | "running" | "cancel_requested" | "cancelled" | "success" | "failed";
  "progress": number;
  "config": Record<string, unknown>;
  "input_schema_version": string | null;
  "input_snapshot_hash": string | null;
  "engine_version": string | null;
  "engine_commit": string | null;
  "snapshot_summary"?: Record<string, unknown> | null;
  "queue_job_id": string | null;
  "worker_id": string | null;
  "queued_time": string | null;
  "heartbeat_time": string | null;
  "cancel_requested": boolean;
  "retry_count": number;
  "retry_reason": string | null;
  "current_simulation_time": number | null;
  "current_cfl": number | null;
  "diagnostics": Record<string, unknown> | null;
  "result_path": string | null;
  "error_message": string | null;
  "created_time": string;
  "start_time": string | null;
  "end_time": string | null;
}

export interface SystemInfoResponse {
  "name": string;
  "version": string;
  "description": string;
  "status": "running";
}

export interface TaskSnapshotResponse {
  "task_id": number;
  "input_schema_version": string;
  "input_snapshot_hash": string;
  "engine_version": string;
  "engine_commit": string;
  "snapshot": Record<string, unknown>;
}

export interface TopologyGenerateRequest {
  "dataset_version_id": number;
  "tolerance"?: number;
}

export interface TopologyResponse {
  "dataset_version_id": number;
  "nodes": Array<RiverNodeRecord>;
  "segments": Array<RiverSegmentRecord>;
  "connections": Array<RiverConnectionRecord>;
}

export interface ValidationError {
  "loc": Array<string | number>;
  "msg": string;
  "type": string;
}

export interface ValidationItem {
  "code": string;
  "category": "spatial" | "hydraulic" | "structure" | "topology" | "model";
  "severity": "error" | "warning" | "passed";
  "message": string;
  "count": number;
  "sample_ids"?: Array<number>;
}

export interface ValidationRequest {
  "dataset_version_id": number;
}

export interface ValidationSummary {
  "errors": number;
  "warnings": number;
  "passed": number;
  "is_model_ready": boolean;
}

export type ValidationReport = app__validation__schemas__ValidationReport;
export type DispatchValidationReport = app__dispatch__schemas__ValidationReport;
export interface GISListQuery { bbox?: string; limit?: number; offset?: number; }
export interface DatabaseListQuery { dataset_version_id?: number; river_id?: number; search?: string; limit?: number; offset?: number; }
export interface DispatchListQuery { dataset_version_id?: number; plan_id?: number; status?: string; limit?: number; offset?: number; }
export interface PageResult<T> { items: T[]; total: number; limit: number; offset: number; }
export type ImportResource = 'rivers' | 'cross_sections' | 'gates' | 'pumps';

function toQuery<T extends object>(params: T): string {
  const query = new URLSearchParams();
  Object.entries(params as Record<string, string | number | undefined>).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)); });
  const value = query.toString();
  return value ? `?${value}` : '';
}

async function requestJson<T>(path: string, options: RequestInit = {}, baseUrl = ''): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `API 请求失败：${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function jsonOptions(method: 'POST' | 'PUT' | 'PATCH', body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

export const getSystemInfo = (baseUrl = '') => requestJson<SystemInfoResponse>('/', {}, baseUrl);
export const getHealth = (baseUrl = '') => requestJson<HealthResponse>('/api/v1/health', {}, baseUrl);
export const getGISHealth = (baseUrl = '') => requestJson<GISHealthResponse>('/api/v1/gis/health', {}, baseUrl);
export const getGISStatistics = (baseUrl = '') => requestJson<GISStatisticsResponse>('/api/v1/gis/stats', {}, baseUrl);
export const getRivers = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/rivers${toQuery(params)}`, {}, baseUrl);
export const getRiver = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/rivers/${id}`, {}, baseUrl);
export const getGates = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/gates${toQuery(params)}`, {}, baseUrl);
export const getGate = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/gates/${id}`, {}, baseUrl);
export const getPumps = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/pumps${toQuery(params)}`, {}, baseUrl);
export const getPump = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/pumps/${id}`, {}, baseUrl);
export const getCrossSections = (params: GISListQuery = {}, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/cross_sections${toQuery(params)}`, {}, baseUrl);
export const getCrossSection = (id: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/cross_sections/${id}`, {}, baseUrl);

export const listRiverRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<RiverListResponse>(`/api/v1/rivers${toQuery(params)}`, {}, baseUrl);
export const createRiverRecord = (body: RiverCreate, baseUrl = '') => requestJson<RiverRecord>('/api/v1/rivers', jsonOptions('POST', body), baseUrl);
export const updateRiverRecord = (id: number, body: RiverUpdate, baseUrl = '') => requestJson<RiverRecord>(`/api/v1/rivers/${id}`, jsonOptions('PUT', body), baseUrl);
export const deleteRiverRecord = (id: number, baseUrl = '') => requestJson<void>(`/api/v1/rivers/${id}`, { method: 'DELETE' }, baseUrl);
export const generateTopology = (body: TopologyGenerateRequest, baseUrl = '') => requestJson<TopologyResponse>('/api/v1/rivers/topology/generate', jsonOptions('POST', body), baseUrl);
export const getTopology = (datasetVersionId: number, baseUrl = '') => requestJson<TopologyResponse>(`/api/v1/rivers/topology?dataset_version_id=${datasetVersionId}`, {}, baseUrl);

export const listCrossSectionRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<CrossSectionListResponse>(`/api/v1/cross-sections${toQuery(params)}`, {}, baseUrl);
export const createCrossSectionRecord = (body: CrossSectionCreate, baseUrl = '') => requestJson<CrossSectionRecord>('/api/v1/cross-sections', jsonOptions('POST', body), baseUrl);
export const updateCrossSectionRecord = (id: number, body: CrossSectionUpdate, baseUrl = '') => requestJson<CrossSectionRecord>(`/api/v1/cross-sections/${id}`, jsonOptions('PUT', body), baseUrl);
export const deleteCrossSectionRecord = (id: number, baseUrl = '') => requestJson<void>(`/api/v1/cross-sections/${id}`, { method: 'DELETE' }, baseUrl);

export const listGateRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<GateListResponse>(`/api/v1/gates${toQuery(params)}`, {}, baseUrl);
export const createGateRecord = (body: GateCreate, baseUrl = '') => requestJson<GateRecord>('/api/v1/gates', jsonOptions('POST', body), baseUrl);
export const updateGateRecord = (id: number, body: GateUpdate, baseUrl = '') => requestJson<GateRecord>(`/api/v1/gates/${id}`, jsonOptions('PUT', body), baseUrl);
export const deleteGateRecord = (id: number, baseUrl = '') => requestJson<void>(`/api/v1/gates/${id}`, { method: 'DELETE' }, baseUrl);

export const listPumpRecords = (params: DatabaseListQuery = {}, baseUrl = '') => requestJson<PumpListResponse>(`/api/v1/pumps${toQuery(params)}`, {}, baseUrl);
export const createPumpRecord = (body: PumpCreate, baseUrl = '') => requestJson<PumpRecord>('/api/v1/pumps', jsonOptions('POST', body), baseUrl);
export const updatePumpRecord = (id: number, body: PumpUpdate, baseUrl = '') => requestJson<PumpRecord>(`/api/v1/pumps/${id}`, jsonOptions('PUT', body), baseUrl);
export const deletePumpRecord = (id: number, baseUrl = '') => requestJson<void>(`/api/v1/pumps/${id}`, { method: 'DELETE' }, baseUrl);

export const getDatasetVersions = (baseUrl = '') => requestJson<Array<DatasetVersionRecord>>('/api/v1/model-data/dataset-versions', {}, baseUrl);
export const getModelParameters = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<ModelParameterRecord>>(`/api/v1/model-data/parameters${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getBoundaryConditions = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<BoundaryConditionRecord>>(`/api/v1/model-data/boundary-conditions${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getSimulationCases = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<SimulationCaseRecord>>(`/api/v1/model-data/simulation-cases${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getModelInput = (caseId: number, baseUrl = '') => requestJson<ModelInputSnapshot>(`/api/v1/model-data/simulation-cases/${caseId}/input`, {}, baseUrl);
export const runValidation = (datasetVersionId: number, baseUrl = '') => requestJson<ValidationReport>('/api/v1/validation/run', jsonOptions('POST', { dataset_version_id: datasetVersionId }), baseUrl);

export const createHydraulicTask = (body: SimulationTaskCreate, baseUrl = '') => requestJson<SimulationTaskRecord>('/api/v1/model/tasks', jsonOptions('POST', body), baseUrl);
export const listHydraulicTasks = (baseUrl = '') => requestJson<Array<SimulationTaskRecord>>('/api/v1/model/tasks', {}, baseUrl);
export const getHydraulicTask = (taskId: number, baseUrl = '') => requestJson<SimulationTaskRecord>(`/api/v1/model/tasks/${taskId}`, {}, baseUrl);
export const runHydraulicTask = (taskId: number, baseUrl = '') => requestJson<SimulationTaskRecord>(`/api/v1/model/tasks/${taskId}/run`, { method: 'POST' }, baseUrl);
export const enqueueHydraulicTask = (taskId: number, baseUrl = '') => requestJson<SimulationTaskRecord>(`/api/v1/model/tasks/${taskId}/enqueue`, { method: 'POST' }, baseUrl);
export const cancelHydraulicTask = (taskId: number, baseUrl = '') => requestJson<SimulationTaskRecord>(`/api/v1/model/tasks/${taskId}/cancel`, { method: 'POST' }, baseUrl);
export const retryHydraulicTask = (taskId: number, baseUrl = '') => requestJson<SimulationTaskRecord>(`/api/v1/model/tasks/${taskId}/retry`, { method: 'POST' }, baseUrl);
export const getHydraulicTaskSnapshot = (taskId: number, baseUrl = '') => requestJson<TaskSnapshotResponse>(`/api/v1/model/tasks/${taskId}/snapshot`, {}, baseUrl);
export const getHydraulicResult = (taskId: number, sectionId?: number, baseUrl = '') => requestJson<SimulationResultResponse>(`/api/v1/model/results/${taskId}${toQuery({ section_id: sectionId })}`, {}, baseUrl);

export const listDispatchPlans = (params: DispatchListQuery = {}, baseUrl = '') => requestJson<PageResult<DispatchPlanRecord>>(`/api/v1/dispatch/plans${toQuery(params)}`, {}, baseUrl);
export const createDispatchPlan = (body: DispatchPlanCreate, baseUrl = '') => requestJson<DispatchPlanRecord>('/api/v1/dispatch/plans', jsonOptions('POST', body), baseUrl);
export const getDispatchPlan = (planId: number, baseUrl = '') => requestJson<DispatchPlanRecord>(`/api/v1/dispatch/plans/${planId}`, {}, baseUrl);
export const updateDispatchPlan = (planId: number, body: DispatchPlanUpdate, baseUrl = '') => requestJson<DispatchPlanRecord>(`/api/v1/dispatch/plans/${planId}`, jsonOptions('PATCH', body), baseUrl);
export const deleteDispatchPlan = (planId: number, baseUrl = '') => requestJson<void>(`/api/v1/dispatch/plans/${planId}`, { method: 'DELETE' }, baseUrl);
export const cloneDispatchPlan = (planId: number, baseUrl = '') => requestJson<DispatchPlanRecord>(`/api/v1/dispatch/plans/${planId}/clone`, { method: 'POST' }, baseUrl);
export const validateDispatchPlan = (planId: number, baseUrl = '') => requestJson<DispatchValidationReport>(`/api/v1/dispatch/plans/${planId}/validate`, { method: 'POST' }, baseUrl);
export const freezeDispatchPlan = (planId: number, baseUrl = '') => requestJson<DispatchPlanRecord>(`/api/v1/dispatch/plans/${planId}/freeze`, { method: 'POST' }, baseUrl);
export const listDispatchActions = (planId: number, baseUrl = '') => requestJson<Array<DispatchActionRecord>>(`/api/v1/dispatch/plans/${planId}/actions`, {}, baseUrl);
export const createDispatchAction = (planId: number, body: DispatchActionCreate, baseUrl = '') => requestJson<DispatchActionRecord>(`/api/v1/dispatch/plans/${planId}/actions`, jsonOptions('POST', body), baseUrl);
export const updateDispatchAction = (actionId: number, body: DispatchActionUpdate, baseUrl = '') => requestJson<DispatchActionRecord>(`/api/v1/dispatch/actions/${actionId}`, jsonOptions('PATCH', body), baseUrl);
export const deleteDispatchAction = (actionId: number, baseUrl = '') => requestJson<void>(`/api/v1/dispatch/actions/${actionId}`, { method: 'DELETE' }, baseUrl);
export const listDispatchRules = (planId: number, baseUrl = '') => requestJson<Array<DispatchRuleRecord>>(`/api/v1/dispatch/plans/${planId}/rules`, {}, baseUrl);
export const createDispatchRule = (planId: number, body: DispatchRuleCreate, baseUrl = '') => requestJson<DispatchRuleRecord>(`/api/v1/dispatch/plans/${planId}/rules`, jsonOptions('POST', body), baseUrl);
export const updateDispatchRule = (ruleId: number, body: DispatchRuleUpdate, baseUrl = '') => requestJson<DispatchRuleRecord>(`/api/v1/dispatch/rules/${ruleId}`, jsonOptions('PATCH', body), baseUrl);
export const deleteDispatchRule = (ruleId: number, baseUrl = '') => requestJson<void>(`/api/v1/dispatch/rules/${ruleId}`, { method: 'DELETE' }, baseUrl);
export const createDispatchRun = (planId: number, baseUrl = '') => requestJson<DispatchRunRecord>(`/api/v1/dispatch/plans/${planId}/runs`, { method: 'POST' }, baseUrl);
export const listDispatchRuns = (params: DispatchListQuery = {}, baseUrl = '') => requestJson<PageResult<DispatchRunRecord>>(`/api/v1/dispatch/runs${toQuery(params)}`, {}, baseUrl);
export const getDispatchRun = (runId: number, baseUrl = '') => requestJson<DispatchRunRecord>(`/api/v1/dispatch/runs/${runId}`, {}, baseUrl);
export const cancelDispatchRun = (runId: number, baseUrl = '') => requestJson<DispatchRunRecord>(`/api/v1/dispatch/runs/${runId}/cancel`, { method: 'POST' }, baseUrl);
export const retryDispatchRun = (runId: number, baseUrl = '') => requestJson<DispatchRunRecord>(`/api/v1/dispatch/runs/${runId}/retry`, { method: 'POST' }, baseUrl);
export const getDispatchComparison = (runId: number, baseUrl = '') => requestJson<DispatchComparison>(`/api/v1/dispatch/runs/${runId}/comparison`, {}, baseUrl);
export const getDispatchEvents = (runId: number, baseUrl = '') => requestJson<Array<Record<string, unknown>>>(`/api/v1/dispatch/runs/${runId}/events`, {}, baseUrl);
export const getDispatchStructures = (runId: number, baseUrl = '') => requestJson<Array<Record<string, unknown>>>(`/api/v1/dispatch/runs/${runId}/structures`, {}, baseUrl);
export const getDispatchNodes = (runId: number, baseUrl = '') => requestJson<Array<Record<string, unknown>>>(`/api/v1/dispatch/runs/${runId}/nodes`, {}, baseUrl);

export const createOptimizationTask = (body: OptimizationTaskCreate, baseUrl = '') => requestJson<OptimizationTaskRecord>('/api/v1/optimization/tasks', jsonOptions('POST', body), baseUrl);
export const listOptimizationTasks = (baseUrl = '') => requestJson<Array<OptimizationTaskRecord>>('/api/v1/optimization/tasks', {}, baseUrl);
export const getOptimizationTask = (taskId: number, baseUrl = '') => requestJson<OptimizationTaskRecord>(`/api/v1/optimization/tasks/${taskId}`, {}, baseUrl);
export const runOptimizationTask = (taskId: number, baseUrl = '') => requestJson<OptimizationTaskRecord>(`/api/v1/optimization/tasks/${taskId}/run`, { method: 'POST' }, baseUrl);
export const cancelOptimizationTask = (taskId: number, baseUrl = '') => requestJson<OptimizationTaskRecord>(`/api/v1/optimization/tasks/${taskId}/cancel`, { method: 'POST' }, baseUrl);
export const getOptimizationCandidates = (taskId: number, baseUrl = '') => requestJson<Array<OptimizationCandidateRecord>>(`/api/v1/optimization/tasks/${taskId}/candidates`, {}, baseUrl);
export const getOptimizationPareto = (taskId: number, baseUrl = '') => requestJson<Array<ParetoCandidateRecord>>(`/api/v1/optimization/tasks/${taskId}/pareto`, {}, baseUrl);
export const getOptimizationRecommendation = (taskId: number, baseUrl = '') => requestJson<RecommendationResponse>(`/api/v1/optimization/tasks/${taskId}/recommendation`, {}, baseUrl);
export const explainOptimizationRecommendation = (taskId: number, baseUrl = '') => requestJson<OptimizationExplanation>(`/api/v1/optimization/tasks/${taskId}/explain`, {}, baseUrl);

export async function uploadDataFile(kind: 'excel' | 'csv' | 'geojson', resource: ImportResource, datasetVersionId: number, file: File, baseUrl = ''): Promise<ImportResponse> {
  const body = new FormData();
  body.set('resource', resource);
  body.set('dataset_version_id', String(datasetVersionId));
  body.set('file', file);
  return requestJson<ImportResponse>(`/api/v1/import/${kind}`, { method: 'POST', body }, baseUrl);
}
