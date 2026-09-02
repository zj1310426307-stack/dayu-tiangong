/* 本文件由 npm run openapi:update 自动生成，请勿手工修改。 */

export interface AcceptanceCriteria {
  "maximum_water_level_rmse"?: number | null;
  "maximum_discharge_rmse"?: number | null;
  "maximum_peak_relative_error"?: number | null;
  "maximum_peak_time_error_seconds"?: number | null;
  "minimum_nse"?: number | null;
  "minimum_r_squared"?: number | null;
  "minimum_observation_coverage"?: number;
  "maximum_mass_balance_relative_error"?: number | null;
}

export interface AcceptanceEvaluation {
  "criteria_passed": boolean;
  "model_state": "DRAFT" | "QA_PASSED" | "CALIBRATED" | "VALIDATED" | "PRODUCTION_APPROVED";
  "checks": Array<Record<string, unknown>>;
  "professional_approval_required"?: boolean;
}

export interface AcceptanceEvaluationRequest {
  "metrics": Array<HydraulicMetrics>;
  "criteria": AcceptanceCriteria;
  "independence": ValidationIndependenceResult;
  "mass_balance_relative_error"?: number | null;
}

export interface AcceptanceManifest {
  "schema_version"?: "dayu-production-acceptance-v1";
  "generated_at"?: string;
  "manifest_hash": string;
  "evidence": Record<string, unknown>;
}

export interface AcceptanceManifestRequest {
  "project": string;
  "model_version": string;
  "qa": Record<string, unknown>;
  "engine": Record<string, unknown>;
  "runtime": Record<string, unknown>;
  "calibration"?: Record<string, unknown> | null;
  "validation"?: Record<string, unknown> | null;
  "comparison"?: Record<string, unknown> | null;
  "run": Record<string, unknown>;
  "metrics": Record<string, unknown>;
  "result_hashes": Record<string, string>;
}

export interface AIChatRequest {
  "question": string;
  "user"?: string;
  "context"?: AIContext;
}

export interface AIChatResponse {
  "conversation_id": number;
  "answer": string;
  "sources": Array<SourceCitation>;
  "tools_used": Array<string>;
  "safety_status": string;
  "provider": string;
  "execution_authorized"?: false;
  "created_time": string;
}

export interface AIContext {
  "dataset_version_id"?: number | null;
  "river_id"?: number | null;
  "simulation_task_id"?: number | null;
  "optimization_task_id"?: number | null;
  "knowledge_document_ids"?: Array<number>;
}

export interface AIToolCallLogRecord {
  "id": number;
  "conversation_id": number | null;
  "tool_name": string;
  "input": Record<string, unknown>;
  "output": Record<string, unknown>;
  "duration_ms": number;
  "time": string;
}

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

export interface AnnotationCollection {
  "items": Array<AnnotationRecord>;
  "total": number;
  "limit": number;
  "offset": number;
  "dataset_version_id": number;
  "scale_denominator": number;
  "renderer"?: "Cesium LabelCollection";
  "demo_data"?: true;
}

export interface AnnotationCreate {
  "dataset_version_id": number;
  "annotation_type": "river" | "gate" | "pump" | "cross_section" | "hydrology_station" | "dispatch_event" | "parameter" | "place";
  "name": string;
  "text": string;
  "description"?: string | null;
  "longitude": number;
  "latitude": number;
  "rotation"?: number;
  "font_size"?: number;
  "color"?: string;
  "visible_scale_min"?: number;
  "visible_scale_max"?: number;
  "related_type"?: "river" | "gate" | "pump" | "cross_section" | "hydrology_station" | "dispatch_event" | null;
  "related_id"?: number | null;
}

export interface AnnotationRecord {
  "dataset_version_id": number;
  "annotation_type": "river" | "gate" | "pump" | "cross_section" | "hydrology_station" | "dispatch_event" | "parameter" | "place";
  "name": string;
  "text": string;
  "description"?: string | null;
  "longitude": number;
  "latitude": number;
  "rotation"?: number;
  "font_size"?: number;
  "color"?: string;
  "visible_scale_min"?: number;
  "visible_scale_max"?: number;
  "related_type"?: "river" | "gate" | "pump" | "cross_section" | "hydrology_station" | "dispatch_event" | null;
  "related_id"?: number | null;
  "id": number;
  "display_text": string;
  "dynamic_lines": Array<string>;
  "dynamic_source": "static" | "simulation" | "dispatch";
  "created_time": string;
}

export interface AnnotationUpdate {
  "annotation_type"?: "river" | "gate" | "pump" | "cross_section" | "hydrology_station" | "dispatch_event" | "parameter" | "place" | null;
  "name"?: string | null;
  "text"?: string | null;
  "description"?: string | null;
  "longitude"?: number | null;
  "latitude"?: number | null;
  "rotation"?: number | null;
  "font_size"?: number | null;
  "color"?: string | null;
  "visible_scale_min"?: number | null;
  "visible_scale_max"?: number | null;
  "related_type"?: "river" | "gate" | "pump" | "cross_section" | "hydrology_station" | "dispatch_event" | null;
  "related_id"?: number | null;
}

export interface app__dispatch__schemas__ValidationReport {
  "plan_id": number;
  "valid": boolean;
  "errors": Array<string>;
  "warnings": Array<string>;
}

export interface app__gis_governance__schemas__ValidationRunRecord {
  "id": number;
  "batch_id": number;
  "ruleset_version": string;
  "status": "running" | "passed" | "failed";
  "staging_content_hash": string;
  "started_at": string;
  "finished_at"?: string | null;
  "summary_json": Record<string, unknown>;
}

export interface app__hydraulic__production__records__ValidationRunRecord {
  "id": number;
  "validation_code": string;
  "production_run_id": number;
  "dataset_version_id": number;
  "case_id": number;
  "calibration_run_id": number | null;
  "status": string;
  "created_at": string;
}

export interface app__validation__schemas__ValidationReport {
  "dataset_version_id": number;
  "checked_time": string;
  "summary": ValidationSummary;
  "items": Array<ValidationItem>;
}

export interface AuditEventRecord {
  "id": number;
  "dataset_version_id": number;
  "action": "IMPORT" | "RUN_CREATION" | "QA_OVERRIDE" | "PARAMETER_PROMOTION" | "CALIBRATION_ACCEPTANCE" | "VALIDATION_ACCEPTANCE" | "PRODUCTION_APPROVAL" | "EXPORT";
  "actor": string;
  "entity_type": string;
  "entity_id": string;
  "content_hash": string;
  "details_json": Record<string, unknown>;
  "created_at": string;
}

export interface BatchCreate {
  "entity_type": "river" | "cross_section" | "gate" | "pump";
  "source_filename": string;
  "source_format": string;
  "source_size": number;
  "source_hash_sha256": string;
  "source_crs": string;
  "target_crs"?: "EPSG:4490";
  "mapping_version": string;
  "operator": string;
  "survey_time"?: string | null;
  "parent_version_id"?: number | null;
  "metadata_json"?: Record<string, unknown>;
  "notes"?: string | null;
}

export interface BatchDiff {
  "batch_id": number;
  "entity_type": "river" | "cross_section" | "gate" | "pump";
  "parent_version_id": number | null;
  "additions": Array<string>;
  "updates": Array<string>;
  "deletions": Array<string>;
  "unchanged": Array<string>;
}

export interface BatchRecord {
  "entity_type": "river" | "cross_section" | "gate" | "pump";
  "source_filename": string;
  "source_format": string;
  "source_size": number;
  "source_hash_sha256": string;
  "source_crs": string;
  "target_crs"?: "EPSG:4490";
  "mapping_version": string;
  "operator": string;
  "survey_time"?: string | null;
  "parent_version_id"?: number | null;
  "metadata_json"?: Record<string, unknown>;
  "notes"?: string | null;
  "id": number;
  "batch_code": string;
  "status": "created" | "staged" | "validating" | "validation_failed" | "validated" | "in_review" | "changes_requested" | "rejected" | "approved" | "promoting" | "promoted" | "published";
  "raw_location"?: string | null;
  "raw_table_name"?: string | null;
  "parent_content_hash"?: string | null;
  "staging_content_hash"?: string | null;
  "promoted_dataset_version_id"?: number | null;
  "staged_by"?: string | null;
  "staged_at"?: string | null;
  "review_submitted_by"?: string | null;
  "review_submitted_at"?: string | null;
  "created_at": string;
  "updated_at": string;
}

export interface BatchStageRequest {
  "actor": string;
  "note"?: string | null;
  "standardization_completed"?: boolean;
}

export interface Body_convert_cog_api_v1_dgis_conversions_cog_post {
  "file": string;
  "target_srid"?: number;
}

export interface Body_convert_geojson_api_v1_dgis_conversions_geojson_post {
  "file": string;
  "target_srid"?: number;
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

export interface Body_import_external_result_api_v1_hydraulic_production_external_results_import_post {
  "file": string;
  "options_json": string;
  "dataset_version_id": number;
  "result_code": string;
  "actor": string;
}

export interface Body_import_geojson_api_v1_import_geojson_post {
  "resource": "rivers" | "cross_sections" | "gates" | "pumps";
  "dataset_version_id": number;
  "file": string;
}

export interface Body_import_observation_api_v1_hydraulic_production_observations_import_post {
  "file": string;
  "options_json": string;
  "dataset_version_id": number;
  "actor": string;
}

export interface Body_import_to_postgis_api_v1_dgis_conversions_postgis_post {
  "file": string;
  "layer_name": string;
  "target_srid"?: number;
  "entity_type"?: "river" | "cross_section" | "gate" | "pump" | null;
  "parent_version_id"?: number | null;
  "operator"?: string;
}

export interface Body_inspect_file_api_v1_dgis_conversions_inspect_post {
  "file": string;
}

export interface Body_preview_external_result_api_v1_hydraulic_production_external_results_preview_post {
  "file": string;
  "options_json": string;
}

export interface Body_preview_import_api_v1_hydraulic_imports_preview_post {
  "dataset_version_id": number;
  "file": string;
  "source_crs": string;
  "engineering_crs": string;
  "coordinate_mode": string;
  "axis_mapping": string;
  "horizontal_unit": string;
  "vertical_datum": string;
  "central_meridian": number;
  "zone_width": number;
  "x_field"?: string;
  "y_field"?: string;
  "z_field"?: string | null;
  "vertical_unit"?: string;
  "zone_prefix_mode"?: string;
}

export interface Body_preview_time_series_api_v1_hydraulic_production_time_series_preview_post {
  "file": string;
  "options_json": string;
}

export interface Body_upload_document_api_v1_ai_knowledge_documents_post {
  "file": string;
  "category": string;
  "version": string;
}

export interface BoundaryConditionCreate {
  "dataset_version_id": number;
  "name": string;
  "boundary_type": "upstream_discharge" | "downstream_water_level" | "lateral_inflow";
  "target_node_id"?: number | null;
  "hydraulic_node_id"?: number | null;
  "branch_id"?: number | null;
  "chainage_m"?: number | null;
  "values": Record<string, unknown>;
  "unit": string;
  "description"?: string | null;
}

export interface BoundaryConditionRecord {
  "dataset_version_id": number;
  "name": string;
  "boundary_type": "upstream_discharge" | "downstream_water_level" | "lateral_inflow";
  "target_node_id"?: number | null;
  "hydraulic_node_id"?: number | null;
  "branch_id"?: number | null;
  "chainage_m"?: number | null;
  "values": Record<string, unknown>;
  "unit": string;
  "description"?: string | null;
  "id": number;
}

export interface BoundaryConditionUpdate {
  "name"?: string | null;
  "boundary_type"?: "upstream_discharge" | "downstream_water_level" | "lateral_inflow" | null;
  "target_node_id"?: number | null;
  "hydraulic_node_id"?: number | null;
  "branch_id"?: number | null;
  "chainage_m"?: number | null;
  "values"?: Record<string, unknown> | null;
  "unit"?: string | null;
  "description"?: string | null;
}

export interface BufferAnalysisRequest {
  "dataset_version_id": number;
  "object_type": "river" | "gate" | "pump" | "cross_section";
  "object_id": number;
  "distance_m": number;
  "include_types"?: Array<"river" | "gate" | "pump" | "cross_section">;
}

export interface BufferAnalysisResponse {
  "dataset_version_id": number;
  "source": SpatialFeature;
  "distance_m": number;
  "buffer_geometry": Record<string, unknown>;
  "impacted": Array<SpatialFeature>;
  "distance_basis"?: "PostGIS geography metres";
}

export interface CalibrationCandidate {
  "candidate_id": string;
  "overrides": Record<string, number>;
  "metrics"?: Array<HydraulicMetrics>;
  "task_id"?: number | null;
  "status"?: "planned" | "queued" | "running" | "completed" | "failed" | "cancelled";
  "objective_score"?: number | null;
  "rank"?: number | null;
  "qualified"?: boolean;
}

export interface CalibrationObjective {
  "mode": "water-level-focused" | "discharge-focused" | "multi-metric";
  "weights": Record<string, number>;
}

export interface CalibrationParameter {
  "group_id": string;
  "parameter"?: "manning_n";
  "target_ids": Array<string>;
  "values": Array<number>;
}

export interface CalibrationPromotionRequest {
  "candidate_id": string;
  "accepted_by": string;
  "acceptance_reason": string;
  "acceptance_criteria": AcceptanceCriteria;
}

export interface CalibrationPromotionResponse {
  "calibration": CalibrationRunRecord;
  "production_run": ProductionRunRecord;
}

export interface CalibrationRankingRequest {
  "candidates": Array<CalibrationCandidate>;
  "objective": CalibrationObjective;
}

export interface CalibrationRunCommitRequest {
  "run_code": string;
  "calibration_run_id"?: number | null;
  "production_run_id": number;
  "dataset_version_id": number;
  "case_id": number;
  "actor": string;
  "dataset": DatasetWindow;
  "sweep": ParameterSweepRequest;
  "objective": CalibrationObjective;
  "metric_evidence": Array<MetricEvidenceRequest>;
  "candidates": Array<CalibrationCandidate>;
}

export interface CalibrationRunRecord {
  "id": number;
  "run_code": string;
  "production_run_id": number;
  "dataset_version_id": number;
  "case_id": number;
  "status": string;
  "selected_candidate_id": string | null;
  "accepted_by": string | null;
  "accepted_at": string | null;
  "created_at": string;
}

export interface CalibrationSweepCreateRequest {
  "run_code": string;
  "production_run_id": number;
  "actor": string;
  "dataset": DatasetWindow;
  "sweep": ParameterSweepRequest;
  "objective": CalibrationObjective;
  "metric_evidence": Array<MetricEvidenceRequest>;
}

export interface CalibrationSweepRunResponse {
  "run": CalibrationRunRecord;
  "candidates": Array<CalibrationCandidate>;
}

export interface CatalogBasemap {
  "basemap_key": string;
  "title": string;
  "type"?: "XYZ";
  "endpoint": string;
  "crs"?: "EPSG:3857";
  "visible"?: boolean;
  "opacity"?: number;
  "min_zoom"?: number;
  "max_zoom": number;
  "credit": string;
}

export interface CatalogCapabilities {
  "identify": boolean;
  "legend": boolean;
  "measure": boolean;
  "version_switch": boolean;
  "editing"?: false;
  "three_d"?: false;
}

export interface CatalogDataset {
  "dataset_version_id": number;
  "version": string;
  "name": string;
  "status": "published";
  "content_hash": string;
  "published_at": string;
  "change_summary": string | null;
}

export interface CatalogFeature {
  "id": string;
  "geometry"?: Record<string, unknown> | null;
  "properties": Record<string, unknown>;
}

export interface CatalogGroup {
  "group_key": string;
  "title": string;
  "order": number;
  "collapsed"?: boolean;
}

export interface CatalogLayer {
  "key": string;
  "title": string;
  "group_key": string;
  "group_title": string;
  "order": number;
  "z_index": number;
  "geometry_type": string;
  "service_key"?: "geoserver_ogc";
  "service_mode"?: "GEOSERVER_WMS";
  "render_mode"?: "RASTER_WMS";
  "layer_name": string;
  "dataset_version_id": number;
  "default_visible": boolean;
  "default_opacity": number;
  "identify_enabled": boolean;
  "legend_enabled": boolean;
  "search_enabled": boolean;
  "detail_route_key": string | null;
  "model_entity_type": string | null;
  "cache_mode": "CLIENT_PRIVATE" | "VERSIONED_PUBLIC";
  "capabilities": Record<string, boolean>;
}

export interface CatalogProject {
  "project_key": string;
  "title": string;
  "native_crs"?: "EPSG:4490";
  "web_crs"?: "EPSG:3857";
}

export interface CatalogService {
  "service_key"?: "geoserver_ogc";
  "service_mode"?: "GEOSERVER_WMS";
  "endpoint"?: "/api/v1/gis/ogc/wms";
  "health_endpoint"?: "/api/v1/gis/geoserver/health";
  "wms_version"?: "1.1.1";
  "healthy": boolean;
}

export interface ComparisonStructureSample {
  "structure_type": "gate" | "pump";
  "structure_id": number;
  "name": string;
  "longitude": number;
  "latitude": number;
  "baseline_value": number | null;
  "comparison_value": number | null;
  "value_difference": number | null;
  "baseline_flow": number | null;
  "comparison_flow": number | null;
  "flow_difference": number | null;
}

export interface ComparisonWaterSample {
  "section_id": number;
  "section_code": string;
  "river_id": number;
  "longitude": number;
  "latitude": number;
  "baseline_water_level": number;
  "comparison_water_level": number;
  "water_level_difference": number;
  "baseline_velocity": number;
  "comparison_velocity": number;
  "velocity_difference": number;
  "baseline_flow": number;
  "comparison_flow": number;
  "flow_difference": number;
}

export interface CompiledControlCommand {
  "time_seconds": number;
  "structure_type": "gate" | "pump";
  "structure_id": number;
  "command_type": string;
  "requested_value": number;
  "resolved_value": number;
  "native_target_value": number;
  "bmi_variable": string;
  "source_type": "manual" | "rule";
  "source_id": number | null;
  "constraint_outcome": "selected" | "limited" | "rejected";
  "constraint_reason"?: string | null;
}

export interface ConstraintConfig {
  "maximum_actions_per_asset"?: number;
  "maximum_pump_starts"?: number;
  "invalid_penalty"?: number;
  "hydraulic_limits"?: HydraulicLimits;
}

export interface ControlCompileIssue {
  "code": string;
  "message": string;
  "structure_type"?: "gate" | "pump" | null;
  "structure_id"?: number | null;
  "source_id"?: number | null;
}

export interface ConversionCapabilityResponse {
  "status": "online" | "offline";
  "gdal_version": string | null;
  "vector_inputs": Array<string>;
  "raster_inputs": Array<string>;
  "outputs": Array<string>;
  "cad_note": string;
}

export interface ConversionJobResponse {
  "job_id": string;
  "operation": "inspect" | "geojson" | "cog" | "postgis";
  "status": "success";
  "input_format": string;
  "output_format": string;
  "output_name": string | null;
  "details": Record<string, unknown>;
}

export interface CoordinateReferenceSpec {
  "source_crs": string;
  "engineering_crs": string;
  "coordinate_mode": "geographic" | "projected";
  "axis_mapping": "x_easting_y_northing" | "x_northing_y_easting";
  "x_field"?: string;
  "y_field"?: string;
  "z_field"?: string | null;
  "horizontal_unit": "m" | "degree";
  "vertical_unit"?: "m";
  "vertical_datum": string;
  "central_meridian": number;
  "zone_width": 3;
  "zone_prefix_mode"?: "none" | "included" | "stripped";
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
  "status"?: string;
  "parent_version_id"?: number | null;
  "source_batch_id"?: number | null;
  "content_hash"?: string | null;
  "change_summary"?: string | null;
  "reviewed_by"?: string | null;
  "reviewed_at"?: string | null;
  "approved_by"?: string | null;
  "approved_at"?: string | null;
  "published_at"?: string | null;
  "retired_at"?: string | null;
  "created_time": string;
}

export interface DatasetVersionUpdate {
  "name"?: string | null;
  "description"?: string | null;
}

export interface DatasetWindow {
  "dataset_id": string;
  "event_id": string;
  "station_ids": Array<string>;
  "start_time": string;
  "end_time": string;
  "role": "calibration" | "validation";
  "holdout_type": "independent_event" | "temporal_holdout" | "same_data";
}

export interface DGISCatalogResponse {
  "components": Array<DGISComponent>;
  "simulation_layers": Array<SimulationLayerRecord>;
  "vector_tile_template": string;
  "vector_tile_sources": Array<string>;
  "geonode_url": string | null;
  "conversion_formats": Record<string, Array<string>>;
}

export interface DGISComponent {
  "key": "postgis" | "timescaledb" | "geoserver" | "geonode" | "gdal" | "martin" | "titiler" | "cesium";
  "name": string;
  "responsibility": string;
  "status": "online" | "configured" | "optional" | "offline";
  "endpoint"?: string | null;
  "version"?: string | null;
}

export interface DGISHealthResponse {
  "status": "healthy" | "degraded";
  "database"?: "single PostgreSQL/PostGIS instance";
  "timescale_hypertable": boolean;
  "components": Array<DGISComponent>;
  "vector_tile_sources": Array<string>;
  "simulation_layer_count": number;
  "demo_data"?: true;
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

export interface DispatchCapabilityFact {
  "engine": string;
  "engine_version": string;
  "adapter_version": string;
  "feature": string;
  "status": string;
  "reason": string;
  "benchmark_ids": Array<string>;
  "verified_at"?: string | null;
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

export interface DispatchExecutionReadiness {
  "plan_id": number;
  "plan_status": "draft" | "validated" | "frozen" | "archived";
  "planning_valid": boolean;
  "frozen_snapshot_valid": boolean;
  "static_preview_allowed": boolean;
  "hydraulic_runtime_supported": false;
  "run_allowed": boolean;
  "evidence_class": "SYNTHETIC_DEVELOPMENT_ONLY";
  "real_validation_status": "SKIPPED_BY_USER";
  "engine": string;
  "engine_version": string;
  "adapter_version": string;
  "runtime_available": boolean;
  "runtime_detail": string;
  "required_features": Array<string>;
  "capabilities": Array<DispatchCapabilityFact>;
  "blockers": Array<DispatchReadinessIssue>;
  "warnings": Array<DispatchReadinessIssue>;
  "frozen_snapshot_hash": string | null;
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
  "snapshot_target"?: "static_v2" | "hydraulic_v3";
  "cloned_from_plan_id"?: number | null;
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

export interface DispatchReadinessIssue {
  "code": string;
  "message": string;
  "feature"?: string | null;
  "status"?: string | null;
}

export interface DispatchReplayRuleEvent {
  "time_seconds": number;
  "event_type": "triggered" | "recovered";
  "rule_id": number | null;
  "action_template": Record<string, unknown>;
}

export interface DispatchReplayStep {
  "time_seconds": number;
  "targets": Array<DispatchReplayTargetRecord>;
  "conflict_evaluations": number;
  "rule_events": Array<DispatchReplayRuleEvent>;
}

export interface DispatchReplayTargetRecord {
  "structure_type": "gate" | "pump";
  "structure_id": number;
  "command_type": string;
  "requested_value": number;
  "resolved_value": number | null;
  "priority": number;
  "source_type": "manual" | "rule";
  "source_id": number | null;
  "outcome": "selected" | "limited" | "rejected";
  "reason": string | null;
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
  "run_mode"?: "legacy" | "hydraulic_preview" | "production";
  "evidence_class"?: string | null;
  "engine_id"?: string | null;
  "control_runtime"?: string | null;
  "compiled_artifact_hash"?: string | null;
  "runtime_provenance"?: Record<string, unknown> | null;
  "result_contract"?: Record<string, unknown> | null;
  "created_time": string;
  "start_time": string | null;
  "end_time": string | null;
}

export interface DispatchSchedulePreview {
  "plan_id": number;
  "evidence_class": "SYNTHETIC_DEVELOPMENT_ONLY";
  "hydraulic_execution_supported": false;
  "no_hydraulic_feedback": true;
  "plan_snapshot_hash": string;
  "observation_hash": string;
  "result_hash": string;
  "steps": Array<DispatchReplayStep>;
  "conflict_evaluations": number;
  "rule_trigger_count": number;
  "rule_recovery_count": number;
  "evaluator_id": string;
  "tie_break_policy": string;
  "initial_state_basis": string;
  "safety_notice": string;
}

export interface DispatchSchedulePreviewRequest {
  "evidence_class": "SYNTHETIC_DEVELOPMENT_ONLY";
  "observations": Array<DispatchSyntheticObservationFrame>;
}

export interface DispatchSyntheticObservationFrame {
  "time_seconds": number;
  "values"?: Array<DispatchSyntheticObservationValue>;
}

export interface DispatchSyntheticObservationValue {
  "observation_type": "node_water_level" | "section_water_level" | "gate_head_difference" | "pump_intake_level";
  "observation_object_id": number;
  "value": number;
}

export interface DRTCCompileReport {
  "compiler_version": string;
  "pinned_runtime_tag"?: "DIMRset_2026.02";
  "status": "COMPILED" | "UNSUPPORTED";
  "rules": Array<DRTCRuleCompileRecord>;
  "artifact_hash": string;
  "runtime_validated": boolean;
}

export interface DRTCRuleCompileRecord {
  "rule_id": number | null;
  "status": "COMPILED" | "UNSUPPORTED";
  "source_semantics": Record<string, unknown>;
  "target_semantics": Record<string, unknown> | null;
  "compiled_component": string | null;
  "warnings"?: Array<string>;
  "unsupported_reason"?: string | null;
}

export interface ExternalComparisonRequest {
  "dayu_series": Array<ProductionSeries>;
  "external_series": Array<ProductionSeries>;
  "alignment": TimeAlignmentOptions;
}

export interface ExternalComparisonResult {
  "metrics": Array<HydraulicMetrics>;
  "longitudinal": Array<Record<string, unknown>>;
  "time_series": Array<Record<string, unknown>>;
  "reference_not_ground_truth"?: boolean;
}

export interface ExternalResultPoint {
  "external_branch": string;
  "branch_id": string;
  "external_chainage": number;
  "chainage_m": number;
  "time_seconds": number;
  "timestamp"?: string | null;
  "water_level_m"?: number | null;
  "discharge_m3s"?: number | null;
  "velocity_m_s"?: number | null;
}

export interface ExternalResultPreview {
  "source_filename": string;
  "source_sha256": string;
  "row_count": number;
  "branch_count": number;
  "variables": Array<"water_level" | "discharge" | "velocity">;
  "issues": Array<QAIssue>;
  "points": Array<ExternalResultPoint>;
  "provenance": Record<string, unknown>;
}

export interface ExternalResultRecord {
  "id": number;
  "dataset_version_id": number;
  "result_code": string;
  "external_model_name": string;
  "external_model_version": string;
  "scenario": string;
  "vertical_datum": string;
  "source_filename": string;
  "source_sha256": string;
  "imported_at": string;
}

export interface FeatureStateCollection {
  "items": Array<FeatureStateRecord>;
  "total": number;
  "dataset_version_id": number;
  "storage"?: "TimescaleDB hypertable + PostGIS";
  "crs"?: "EPSG:4490";
  "demo_data"?: true;
}

export interface FeatureStateCreate {
  "dataset_version_id": number;
  "feature_type": "water_level" | "flow" | "rainfall" | "gate" | "pump" | "flood_risk";
  "feature_id": number;
  "timestamp": string;
  "state_json": Record<string, unknown>;
  "geometry": PointGeometry;
  "source": "observation" | "simulation" | "dispatch" | "import";
  "task_id"?: number | null;
}

export interface FeatureStateRecord {
  "dataset_version_id": number;
  "feature_type": "water_level" | "flow" | "rainfall" | "gate" | "pump" | "flood_risk";
  "feature_id": number;
  "timestamp": string;
  "state_json": Record<string, unknown>;
  "geometry": PointGeometry;
  "source": "observation" | "simulation" | "dispatch" | "import";
  "task_id"?: number | null;
  "id": number;
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

export interface GeoServerConfigResponse {
  "workspace"?: "dayu";
  "wms_url": string;
  "wmts_url": string;
  "wfs_url": string;
  "preferred_wmts_matrix_set"?: "EPSG:900913";
  "interaction_source"?: "FastAPI /api/v1/gis/*";
}

export interface GeoServerHealthResponse {
  "status": "healthy";
  "workspace"?: "dayu";
  "layers": number;
  "cached_layers": number;
  "basemap_group"?: "dayu_basemap";
  "wms"?: "online";
  "wmts"?: "online";
  "wfs_mode"?: "basic-read-only";
  "source"?: "PostGIS / CGCS2000";
}

export interface GeoServerLayerRecord {
  "name": string;
  "qualified_name": string;
  "title": string;
  "geometry_type": "LineString" | "MultiLineString" | "Point" | "Polygon" | "MultiPolygon";
  "style": string;
  "wms_enabled"?: true;
  "wmts_cached": boolean;
  "srid"?: 4490;
}

export interface GISCatalogResponse {
  "schema_version"?: "gis-catalog/v1";
  "catalog_revision": string;
  "generated_at": string;
  "project": CatalogProject;
  "dataset": CatalogDataset;
  "capabilities": CatalogCapabilities;
  "services": Array<CatalogService>;
  "groups": Array<CatalogGroup>;
  "layers": Array<CatalogLayer>;
  "basemaps": Array<CatalogBasemap>;
}

export interface GISComparisonFrame {
  "dataset_version_id": number;
  "baseline_task_id": number;
  "comparison_task_id": number;
  "baseline_dispatch_run_id"?: number | null;
  "comparison_dispatch_run_id"?: number | null;
  "requested_time_seconds": number;
  "baseline_time_seconds"?: number | null;
  "comparison_time_seconds"?: number | null;
  "water_samples": Array<ComparisonWaterSample>;
  "structure_samples": Array<ComparisonStructureSample>;
  "execution_authorized"?: false;
  "demo_data"?: true;
}

export interface GISFeatureInfoResponse {
  "layer_key": string;
  "dataset_version_id": number;
  "crs"?: "EPSG:3857";
  "features": Array<CatalogFeature>;
}

export interface GISHealthResponse {
  "status": "healthy";
  "database": string;
  "postgis_version": string;
  "srid"?: 4490;
}

export interface GISInteractionFrame {
  "dataset_version_id": number;
  "task_id"?: number | null;
  "dispatch_run_id"?: number | null;
  "task_status"?: string | null;
  "timeline": Array<number>;
  "requested_time_seconds": number;
  "selected_time_seconds"?: number | null;
  "warning_level": number;
  "danger_level": number;
  "threshold_source": "dispatch_plan" | "demo_default";
  "water_samples": Array<GISWaterSample>;
  "structure_samples": Array<GISStructureSample>;
  "crs"?: "EPSG:4490";
  "demo_data"?: true;
}

export interface GISStatisticsResponse {
  "dataset_version_id": number;
  "rivers": number;
  "gates": number;
  "pumps": number;
  "cross_sections": number;
  "demo_data"?: true;
  "source"?: "PostGIS / DEMO DATA";
}

export interface GISStructureSample {
  "structure_type": "gate" | "pump";
  "structure_id": number;
  "code": string;
  "name": string;
  "longitude": number;
  "latitude": number;
  "requested_value": number | null;
  "actual_value": number | null;
  "flow": number;
  "power_kw": number | null;
  "state": "open" | "closed" | "running" | "stopped" | "unknown";
  "constraint_flags": Array<string>;
}

export interface GISWaterSample {
  "section_id": number;
  "section_code": string;
  "river_id": number;
  "longitude": number;
  "latitude": number;
  "water_level": number;
  "flow": number;
  "velocity": number;
  "risk_level": "normal" | "warning" | "danger";
  "velocity_level": "low" | "medium" | "high";
  "flow_direction": "downstream" | "upstream" | "stationary";
  "flow_bearing_degrees": number;
}

export interface HealthResponse {
  "status": "healthy";
  "service": string;
  "version": string;
}

export interface HTTPValidationError {
  "detail"?: Array<ValidationError>;
}

export interface Hydraulic1DPreviewResponse {
  "readiness": Hydraulic1DReadinessResponse;
  "snapshot_hash"?: string | null;
  "snapshot"?: Record<string, unknown> | null;
}

export interface Hydraulic1DReadinessResponse {
  "case_id": number;
  "ready": boolean;
  "engine_id"?: "mascaret";
  "engine_version"?: "v9.1.1";
  "runtime_available": boolean;
  "runtime_detail": string;
  "runtime_identity": Record<string, unknown>;
  "blockers"?: Array<Record<string, unknown>>;
  "warnings"?: Array<Record<string, unknown>>;
  "input_summary"?: Record<string, unknown> | null;
}

export interface HydraulicBatchProcessRequest {
  "vertical_step_m"?: number;
  "profile_ids": Array<number>;
}

export interface HydraulicBranchActionRecord {
  "branch_id": number;
  "direction_status": string;
  "start_chainage_m": number;
  "end_chainage_m": number;
  "length_m": number;
}

export interface HydraulicBranchInput {
  "code": string;
  "river_name": string;
  "branch_name": string;
  "flow_direction"?: "forward" | "reverse" | "unknown";
  "source_revision"?: string | null;
  "points": Array<HydraulicChainageInput>;
}

export interface HydraulicBranchRecord {
  "id": number;
  "legacy_river_id": number | null;
  "branch_code": string;
  "river_name": string;
  "branch_name": string;
  "start_chainage": number;
  "end_chainage": number;
  "length_m": number;
  "direction_status": string;
  "upstream_node_id": number | null;
  "downstream_node_id": number | null;
  "section_count": number;
  "reach_count": number;
  "reaches"?: Array<HydraulicReachRecord>;
  "sections"?: Array<HydraulicSectionSummary>;
}

export interface HydraulicCapabilityResponse {
  "exchange_profile": string;
  "native_xns11_available": boolean;
  "native_nwk11_available": boolean;
  "supported_imports": Array<string>;
  "supported_exports": Array<string>;
  "source_srids": Array<number>;
  "engineering_srids": Array<number>;
  "axis_mappings": Array<string>;
  "limitation": string;
}

export interface HydraulicChainageInput {
  "chainage": number;
  "x": number;
  "y": number;
  "z"?: number | null;
  "point_code"?: string | null;
}

export interface HydraulicCompileIssue {
  "stage": "plan" | "hydraulic_model" | "capability" | "asset_mapping" | "gate_mapping" | "pump_mapping" | "manual_control" | "drtc" | "observation" | "runtime";
  "code": string;
  "message": string;
  "field_path"?: string | null;
  "structure_type"?: "gate" | "pump" | null;
  "structure_id"?: number | null;
}

export interface HydraulicControlCompileReport {
  "compiler_version"?: "dayu.hydraulic-control-compiler.v1";
  "status": "COMPILED" | "UNSUPPORTED";
  "commands"?: Array<CompiledControlCommand>;
  "issues"?: Array<ControlCompileIssue>;
  "artifact_hash": string;
}

export interface HydraulicCrossSectionInput {
  "section_code": string;
  "section_name"?: string | null;
  "branch_code": string;
  "chainage": number;
  "topography_id"?: string;
  "survey_date"?: string | null;
  "survey_method"?: string | null;
  "bed_elevation_m"?: number | null;
  "bed_elevation_source"?: "unconfirmed" | "surveyed" | "design" | "synthetic";
  "bed_elevation_confirmed_by"?: string | null;
  "bed_elevation_confirmed_at"?: string | null;
  "default_manning_n"?: number;
  "location_x"?: number | null;
  "location_y"?: number | null;
  "axis_points"?: Array<Array<unknown>>;
  "roughness_zones"?: Array<HydraulicRoughnessZoneInput>;
  "points": Array<HydraulicSectionPointInput>;
}

export interface HydraulicExchangePayload {
  "network_code": string;
  "network_name": string;
  "source_srid": number;
  "source_kind": "mike11" | "excel" | "csv" | "geojson" | "shp" | "dxf" | "api";
  "coordinate_reference"?: CoordinateReferenceSpec | null;
  "branches"?: Array<HydraulicBranchInput>;
  "sections"?: Array<HydraulicCrossSectionInput>;
}

export interface HydraulicHydraulicRowRecord {
  "stage_m": number;
  "area_m2": number;
  "top_width_m": number;
  "wetted_perimeter_m": number;
  "hydraulic_radius_m": number;
  "conveyance": number;
}

export interface HydraulicImportCommitRequest {
  "job_code": string;
  "preview_config_hash": string;
}

export interface HydraulicImportJobRecord {
  "id": number;
  "job_code": string;
  "dataset_version_id": number;
  "filename": string;
  "source_format": string;
  "source_srid": number;
  "source_hash_sha256": string;
  "config_hash": string;
  "coordinate_reference": CoordinateReferenceSpec;
  "transformation_evidence": Record<string, unknown>;
  "parser_profile": string;
  "status": string;
  "record_counts": Record<string, number>;
  "issues": Array<HydraulicIssue>;
  "native_validation_status": string;
  "created_at": string;
  "completed_at": string | null;
}

export interface HydraulicImportPreview {
  "job": HydraulicImportJobRecord;
  "payload": HydraulicExchangePayload | null;
}

export interface HydraulicIssue {
  "severity": "error" | "warning" | "info" | "passed";
  "code": string;
  "message": string;
  "entity_type"?: string | null;
  "entity_ref"?: string | null;
  "context"?: Record<string, unknown>;
}

export interface HydraulicLimits {
  "maximum_water_level"?: number | null;
  "maximum_flow"?: number | null;
  "maximum_pump_power_kw"?: number | null;
}

export interface HydraulicLocateRequest {
  "snap_tolerance_m"?: number;
  "manual_chainage_m"?: number | null;
  "override_reason"?: string | null;
  "actor"?: string | null;
}

export interface HydraulicMetrics {
  "variable": "water_level" | "discharge" | "velocity";
  "unit": string;
  "alignment_method": string;
  "valid_sample_count": number;
  "observed_sample_count": number;
  "coverage_ratio": number;
  "sufficient_samples": boolean;
  "mae"?: number | null;
  "rmse"?: number | null;
  "bias"?: number | null;
  "nse"?: number | null;
  "r_squared"?: number | null;
  "peak_value_error"?: number | null;
  "peak_relative_error"?: number | null;
  "peak_time_error_seconds"?: number | null;
}

export interface HydraulicModelQARequest {
  "engineering_crs": string;
  "horizontal_unit": string;
  "vertical_datum": string;
  "simulation_duration_seconds": number;
  "branches": Array<ProductionBranch>;
  "cross_sections": Array<ProductionCrossSection>;
  "boundaries": Array<ProductionBoundary>;
  "observations"?: Array<ProductionSeries>;
  "structures"?: Array<ProductionStructure>;
  "thresholds"?: QAThresholds;
}

export interface HydraulicModelQAResult {
  "ruleset_version": string;
  "error_count": number;
  "warning_count": number;
  "info_count": number;
  "run_allowed": boolean;
  "issues": Array<QAIssue>;
  "spacing_statistics"?: Record<string, number | null>;
  "thalweg_profile"?: Array<Record<string, number | string>>;
}

export interface HydraulicNetworkGraphRecord {
  "network_id": number;
  "nodes": Array<Record<string, unknown>>;
  "branches": Array<Record<string, unknown>>;
  "cross_sections": Array<Record<string, unknown>>;
  "structures": Array<HydraulicStructureRecord>;
  "boundaries": Array<Record<string, unknown>>;
}

export interface HydraulicNetworkRecord {
  "id": number;
  "dataset_version_id": number;
  "code": string;
  "name": string;
  "display_crs": string;
  "engineering_crs": string | null;
  "horizontal_unit": string;
  "vertical_datum": string;
  "vertical_unit": string;
  "source_kind": string;
  "branch_count": number;
  "node_count": number;
  "reach_count": number;
  "nodes"?: Array<HydraulicNodeRecord>;
  "branches"?: Array<HydraulicBranchRecord>;
}

export interface HydraulicNodeRecord {
  "id": number;
  "node_code": string;
  "node_name": string | null;
  "node_type": string;
  "geometry": Record<string, unknown>;
}

export interface HydraulicPlanCompileReport {
  "plan_id": number;
  "snapshot_target"?: "hydraulic_v3";
  "target_schema_version"?: "dayu.dispatch-plan.v3";
  "evidence_class"?: "SYNTHETIC_NUMERICAL_ONLY";
  "engine_id"?: "d-flow-fm";
  "engine_version"?: "DIMRset_2026.02";
  "control_runtime"?: "d-rtc/fbc";
  "plan_valid": boolean;
  "hydraulic_model_valid": boolean;
  "capability_valid": boolean;
  "structure_mapping_valid": boolean;
  "manual_control_valid": boolean;
  "drtc_valid": boolean;
  "observation_contract_valid": boolean;
  "ready_to_freeze": boolean;
  "runtime_available": boolean;
  "controlled_runtime_accepted": boolean;
  "ready_to_run": boolean;
  "runtime_detail": string;
  "runtime_provenance"?: Record<string, unknown> | null;
  "capabilities"?: Array<Record<string, unknown>>;
  "hydraulic_model_snapshot_hash"?: string | null;
  "manual_control_report"?: HydraulicControlCompileReport | null;
  "drtc_compile_report"?: DRTCCompileReport | null;
  "issues"?: Array<HydraulicCompileIssue>;
  "warnings"?: Array<HydraulicCompileIssue>;
  "report_hash": string;
  "real_engineering_validation"?: false;
  "real_equipment_command"?: false;
  "plc_scada_connected"?: false;
}

export interface HydraulicPlanCompileRequest {
  "initial_actuator_state": Array<InitialActuatorState>;
  "observation_bindings"?: Array<ObservationBinding>;
  "observation_sampling_interval_seconds": number;
  "runtime_mode"?: "external" | "container";
  "timeout_seconds"?: number;
  "synthetic_fixture"?: true;
}

export interface HydraulicPlanFreezeResponse {
  "plan_id": number;
  "status"?: "frozen";
  "schema_version"?: "dayu.dispatch-plan.v3";
  "snapshot_hash": string;
  "hydraulic_model_snapshot_hash": string;
  "control_contract_hash": string;
  "evidence_class"?: "SYNTHETIC_NUMERICAL_ONLY";
  "runtime_available": boolean;
  "real_engineering_validation"?: false;
  "real_equipment_command"?: false;
  "plc_scada_connected"?: false;
}

export interface HydraulicPreviewJobRecord {
  "job_id": number;
  "run_id": number;
  "evidence_class"?: "SYNTHETIC_NUMERICAL_ONLY";
  "engine"?: "d-flow-fm";
  "control_runtime"?: "d-rtc/fbc";
  "status": "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  "real_engineering_validation"?: false;
  "real_equipment_command"?: false;
  "plc_scada_connected"?: false;
}

export interface HydraulicProcessingRecord {
  "id": number;
  "profile_hash": string;
  "processor_version": string;
  "vertical_step_m": number;
  "status": string;
  "minimum_stage_m": number | null;
  "maximum_stage_m": number | null;
  "generated_at": string | null;
  "diagnostics": Record<string, unknown>;
  "rows"?: Array<HydraulicHydraulicRowRecord>;
}

export interface HydraulicProcessRequest {
  "vertical_step_m"?: number;
}

export interface HydraulicProfileRecord {
  "id": number;
  "topography_id": string;
  "survey_date": string | null;
  "survey_method": string | null;
  "vertical_datum": string;
  "vertical_unit": string;
  "default_manning_n": number;
  "profile_hash": string;
  "is_active": boolean;
  "points": Array<HydraulicSectionPointRecord>;
  "roughness_zones": Array<HydraulicRoughnessZoneRecord>;
  "processing"?: HydraulicProcessingRecord | null;
}

export interface HydraulicReachRecord {
  "id": number;
  "reach_code": string;
  "reach_type": string;
  "start_chainage_m": number;
  "end_chainage_m": number;
  "upstream_node_id": number;
  "downstream_node_id": number;
  "length_m": number;
  "geometry": Record<string, unknown>;
}

export interface HydraulicResultPoint {
  "scenario_id": string;
  "branch_id": string;
  "cross_section_id": string;
  "chainage_m": number;
  "time_seconds": number;
  "water_level_m": number;
  "discharge_m3s": number;
  "velocity_m_s": number;
  "depth_m"?: number | null;
  "flow_area_m2"?: number | null;
  "bed_elevation_m"?: number | null;
  "left_bank_elevation_m"?: number | null;
  "right_bank_elevation_m"?: number | null;
  "geometry"?: Record<string, unknown> | null;
}

export interface HydraulicRoughnessZoneInput {
  "zone_order": number;
  "offset_start_m": number;
  "offset_end_m": number;
  "manning_n": number;
  "zone_type"?: string;
}

export interface HydraulicRoughnessZoneRecord {
  "zone_order": number;
  "offset_start_m": number;
  "offset_end_m": number;
  "manning_n": number;
  "zone_type": string;
}

export interface HydraulicSectionDetail {
  "id": number;
  "dataset_version_id": number;
  "branch_id": number;
  "branch_code": string;
  "legacy_cross_section_id": number | null;
  "section_code": string;
  "section_name": string;
  "chainage": number;
  "computed_chainage_m": number | null;
  "chainage_source": string;
  "snap_distance_m": number | null;
  "orientation_status": string;
  "bed_elevation_m": number | null;
  "bed_elevation_source": string;
  "bed_elevation_confirmed_by": string | null;
  "bed_elevation_confirmed_at": string | null;
  "location_geometry": Record<string, unknown>;
  "axis_geometry": Record<string, unknown> | null;
  "profiles": Array<HydraulicProfileRecord>;
}

export interface HydraulicSectionPointInput {
  "sequence": number;
  "distance": number;
  "elevation": number;
  "marker_type"?: "none" | "left_bank" | "right_bank" | "left_levee" | "right_levee" | "low_flow_left" | "low_flow_right" | "thalweg";
  "point_code"?: string | null;
  "x"?: number | null;
  "y"?: number | null;
  "z"?: number | null;
}

export interface HydraulicSectionPointRecord {
  "sequence": number;
  "distance": number;
  "elevation": number;
  "marker_type": string;
  "point_code": string | null;
  "x"?: number | null;
  "y"?: number | null;
  "z"?: number | null;
}

export interface HydraulicSectionSummary {
  "id": number;
  "section_code": string;
  "chainage": number;
  "topography_id": string;
  "profile_count": number;
  "point_count": number;
  "orientation_status": string;
  "bed_elevation_m": number | null;
  "bed_elevation_source": string;
}

export interface HydraulicStructureCreate {
  "dataset_version_id": number;
  "network_id": number;
  "branch_id": number;
  "structure_code": string;
  "structure_name": string;
  "structure_type": "weir" | "culvert" | "bridge" | "gate" | "sluice" | "pump" | "orifice" | "dam" | "storage_link" | "compound";
  "chainage_m": number;
  "x": number;
  "y": number;
  "crest_elevation_m"?: number | null;
  "invert_elevation_m"?: number | null;
  "width_m"?: number | null;
  "height_m"?: number | null;
  "hydraulic_law_type"?: string;
  "hydraulic_parameters"?: Record<string, unknown>;
  "operation_rule_type"?: "fixed" | "time_series" | "water_level_controlled" | "scenario_specific";
  "operation_parameters"?: Record<string, unknown>;
  "status"?: "draft" | "active" | "inactive" | "retired";
  "metadata"?: Record<string, unknown>;
}

export interface HydraulicStructureRecord {
  "id": number;
  "dataset_version_id": number;
  "network_id": number;
  "branch_id": number;
  "structure_code": string;
  "structure_name": string;
  "structure_type": "weir" | "culvert" | "bridge" | "gate" | "sluice" | "pump" | "orifice" | "dam" | "storage_link" | "compound";
  "chainage_m": number;
  "location_geometry": Record<string, unknown>;
  "crest_elevation_m": number | null;
  "invert_elevation_m": number | null;
  "width_m": number | null;
  "height_m": number | null;
  "hydraulic_law_type": string;
  "hydraulic_parameters": Record<string, unknown>;
  "operation_rule_type": "fixed" | "time_series" | "water_level_controlled" | "scenario_specific";
  "operation_parameters": Record<string, unknown>;
  "status": "draft" | "active" | "inactive" | "retired";
  "metadata": Record<string, unknown>;
  "legacy_gate_id": number | null;
  "legacy_pump_id": number | null;
  "solver_status": string;
  "solver_reason": string;
}

export interface HydraulicStructureScenarioRecord {
  "status_override"?: "draft" | "active" | "inactive" | "retired" | null;
  "hydraulic_parameters_override"?: Record<string, unknown>;
  "operation_rule_type_override"?: "fixed" | "time_series" | "water_level_controlled" | "scenario_specific" | null;
  "operation_parameters_override"?: Record<string, unknown>;
  "metadata"?: Record<string, unknown>;
  "id": number;
  "dataset_version_id": number;
  "case_id": number;
  "structure_id": number;
  "updated_at": string;
}

export interface HydraulicStructureScenarioUpsert {
  "status_override"?: "draft" | "active" | "inactive" | "retired" | null;
  "hydraulic_parameters_override"?: Record<string, unknown>;
  "operation_rule_type_override"?: "fixed" | "time_series" | "water_level_controlled" | "scenario_specific" | null;
  "operation_parameters_override"?: Record<string, unknown>;
  "metadata"?: Record<string, unknown>;
}

export interface HydraulicStructureUpdate {
  "branch_id"?: number | null;
  "structure_code"?: string | null;
  "structure_name"?: string | null;
  "structure_type"?: "weir" | "culvert" | "bridge" | "gate" | "sluice" | "pump" | "orifice" | "dam" | "storage_link" | "compound" | null;
  "chainage_m"?: number | null;
  "x"?: number | null;
  "y"?: number | null;
  "crest_elevation_m"?: number | null;
  "invert_elevation_m"?: number | null;
  "width_m"?: number | null;
  "height_m"?: number | null;
  "hydraulic_law_type"?: string | null;
  "hydraulic_parameters"?: Record<string, unknown> | null;
  "operation_rule_type"?: "fixed" | "time_series" | "water_level_controlled" | "scenario_specific" | null;
  "operation_parameters"?: Record<string, unknown> | null;
  "status"?: "draft" | "active" | "inactive" | "retired" | null;
  "metadata"?: Record<string, unknown> | null;
}

export interface HydraulicTopologyBuildRequest {
  "snap_tolerance_m"?: number;
  "minimum_reach_length_m"?: number;
}

export interface HydraulicTopologyReport {
  "network_id": number;
  "engineering_crs": string;
  "snap_tolerance_m": number;
  "node_count": number;
  "branch_count": number;
  "reach_count": number;
  "issues": Array<HydraulicIssue>;
}

export interface HydraulicValidationRequest {
  "dataset_version_id": number;
}

export interface HydraulicValidationRunRecord {
  "id": number;
  "run_code": string;
  "dataset_version_id": number;
  "status": string;
  "summary": Record<string, unknown>;
  "created_at": string;
  "completed_at": string | null;
  "results": Array<HydraulicIssue>;
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

export interface InitialActuatorState {
  "structure_type": "gate" | "pump";
  "structure_id": number;
  "gate_opening_m"?: number | null;
  "pump_enabled"?: boolean | null;
  "running_units"?: number | null;
  "runtime_seconds"?: number;
  "stop_seconds"?: number;
  "control_state"?: Record<string, string | number | boolean>;
  "evidence": "SOURCE_DATA" | "SYNTHETIC_INITIAL_STATE";
}

export interface KnowledgeDocumentRecord {
  "id": number;
  "name": string;
  "category": string;
  "version": string;
  "source": string;
  "source_type": string;
  "content_hash": string;
  "chunk_count": number;
  "upload_time": string;
  "updated_time": string;
}

export interface KnowledgeSearchItem {
  "document_id": number;
  "document_name": string;
  "category": string;
  "version": string;
  "source": string;
  "location": string;
  "content": string;
  "score": number;
  "updated_time": string;
}

export interface KnowledgeSearchResponse {
  "query": string;
  "items": Array<KnowledgeSearchItem>;
}

export interface LayerCatalogItem {
  "key": string;
  "title": string;
  "group": "base" | "engineering" | "annotation" | "model" | "dispatch" | "analysis";
  "source": "WMS" | "WMTS" | "MVT" | "FastAPI" | "PostGIS analysis";
  "geometry": "raster" | "point" | "line" | "polygon" | "mixed";
  "version_isolated"?: true;
  "default_visible": boolean;
  "dynamic": boolean;
}

export interface LocationSearchItem {
  "result_type": "coordinate" | "administrative_area" | "road" | "place_name" | "water_name" | "poi";
  "object_id"?: number | null;
  "name": string;
  "address"?: string | null;
  "longitude": number;
  "latitude": number;
  "source": "coordinate-parser" | "PostGIS dayu_basemap";
}

export interface LocationSearchResponse {
  "query": string;
  "mode": "coordinate" | "text";
  "dataset_version_id": number;
  "items": Array<LocationSearchItem>;
  "crs"?: "EPSG:4490";
  "demo_data"?: true;
}

export interface MetricEvaluationRequest {
  "observed": ProductionSeries;
  "simulated": ProductionSeries;
  "alignment"?: TimeAlignmentOptions;
}

export interface MetricEvidenceRequest {
  "observation_series_id": number;
  "cross_section_id": number;
  "maximum_chainage_distance_m": number;
  "alignment"?: TimeAlignmentOptions;
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

export interface NearestFacilityRequest {
  "dataset_version_id": number;
  "longitude": number;
  "latitude": number;
  "facility_types"?: Array<"gate" | "pump" | "hydrology_station">;
  "limit"?: number;
  "max_distance_m"?: number | null;
}

export interface NearestFacilityResponse {
  "dataset_version_id": number;
  "origin": Record<string, unknown>;
  "facilities": Array<SpatialFeature>;
  "distance_basis"?: "PostGIS geography metres";
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

export interface ObservationBinding {
  "observation_type": "node_water_level" | "section_water_level" | "gate_head_difference" | "pump_intake_level";
  "observation_object_id": number;
  "source_kind": "observation_point" | "cross_section" | "oriented_observation_pair";
  "source_id"?: string | null;
  "upstream_source_id"?: string | null;
  "downstream_source_id"?: string | null;
  "unit"?: "m";
  "binding_evidence": "SOURCE_DATA" | "SYNTHETIC_ASSUMPTION";
}

export interface ObservationRecord {
  "id": number;
  "dataset_version_id": number;
  "series_code": string;
  "station_id": string;
  "branch_id": number;
  "chainage_m": number;
  "variable": string;
  "unit": string;
  "vertical_datum": string;
  "source_filename": string;
  "source_sha256": string;
  "imported_at": string;
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
  "dataset_version_id": number;
  "bbox"?: Array<number> | null;
  "demo_data"?: true;
  "crs"?: "EPSG:4490";
}

export interface ParameterSweepPlan {
  "total_candidates": number;
  "max_runs": number;
  "candidates": Array<CalibrationCandidate>;
}

export interface ParameterSweepRequest {
  "parameters": Array<CalibrationParameter>;
  "max_runs"?: number;
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

export interface PointGeometry {
  "type"?: "Point";
  "coordinates": Array<unknown>;
}

export interface ProductionApprovalRequest {
  "approved_by": string;
  "approval_reason": string;
}

export interface ProductionBoundary {
  "boundary_id": string;
  "branch_id": string;
  "location": "upstream" | "downstream" | "lateral";
  "chainage_m"?: number | null;
  "series": ProductionSeries;
}

export interface ProductionBranch {
  "branch_id": string;
  "start_chainage_m": number;
  "end_chainage_m": number;
  "direction_confirmed": boolean;
  "centerline": Array<Array<unknown>>;
  "upstream_node_id"?: string | null;
  "downstream_node_id"?: string | null;
}

export interface ProductionCapabilityResponse {
  "framework_version"?: "hydro-1d-production-04-v1";
  "engineering_import": Array<string>;
  "model_qa": boolean;
  "calibration": Array<string>;
  "validation": Array<string>;
  "external_comparison": Array<string>;
  "result_products": Array<string>;
  "real_project_status"?: "DATA_NOT_AVAILABLE";
  "real_project_reason": string;
}

export interface ProductionCrossSection {
  "section_id": string;
  "branch_id": string;
  "chainage_m": number;
  "offsets_m": Array<number>;
  "elevations_m": Array<number>;
  "vertical_datum": string;
  "orientation_confirmed": boolean;
  "axis"?: Array<Array<unknown>>;
  "location"?: Array<unknown> | null;
}

export interface ProductionRunRecord {
  "id": number;
  "run_code": string;
  "dataset_version_id": number;
  "case_id": number;
  "task_id": number | null;
  "qa_run_code": string;
  "model_state": string;
  "input_snapshot_hash": string;
  "mass_balance_relative_error": number | null;
  "approved_by": string | null;
  "approved_at": string | null;
  "created_at": string;
}

export interface ProductionSeries {
  "series_id": string;
  "variable": "water_level" | "discharge" | "velocity";
  "unit": "m" | "m3/s" | "m/s";
  "samples": Array<ProductionSeriesPoint>;
  "source": string;
  "branch_id"?: string | null;
  "chainage_m"?: number | null;
  "station_id"?: string | null;
  "vertical_datum"?: string;
  "time_basis"?: "relative" | "absolute";
  "timezone"?: string | null;
}

export interface ProductionSeriesPoint {
  "time_seconds": number;
  "value"?: number | null;
  "quality_flag"?: "GOOD" | "SUSPECT" | "MISSING" | "REJECTED";
  "timestamp"?: string | null;
}

export interface ProductionStructure {
  "structure_id": string;
  "structure_type": "weir" | "culvert" | "bridge" | "gate" | "sluice" | "pump" | "orifice" | "dam";
  "branch_id": string;
  "chainage_m": number;
  "vertical_datum": string;
  "capability_status": "VERIFIED_NATIVE" | "VERIFIED_EQUIVALENT" | "UNVERIFIED" | "UNSUPPORTED";
  "status"?: "draft" | "active" | "inactive" | "retired";
  "location"?: Array<unknown> | null;
}

export interface ProductionTaskCreateRequest {
  "run_code": string;
  "qa_run_code": string;
  "actor": string;
  "task": SimulationTaskCreate;
  "qa": HydraulicModelQARequest;
}

export interface PromotedVersionRecord {
  "id": number;
  "version": string;
  "name": string;
  "description"?: string | null;
  "creator": string;
  "status": "approved" | "published" | "retired";
  "parent_version_id"?: number | null;
  "source_batch_id"?: number | null;
  "content_hash"?: string | null;
  "change_summary"?: string | null;
  "approved_by"?: string | null;
  "approved_at"?: string | null;
  "published_at"?: string | null;
  "created_time": string;
}

export interface PromoteRequest {
  "version": string;
  "name": string;
  "creator": string;
  "change_summary": string;
}

export interface PublicationRecord {
  "id": number;
  "dataset_version_id": number;
  "publication_status": "pending" | "published" | "failed" | "retired";
  "published_by": string;
  "published_at"?: string | null;
  "previous_publication_id"?: number | null;
  "manifest_json": Record<string, unknown>;
  "created_at": string;
}

export interface PublishRequest {
  "published_by": string;
  "manifest_json"?: Record<string, unknown>;
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

export interface QAIssue {
  "code": string;
  "severity": "ERROR" | "WARNING" | "INFO";
  "category": "Network" | "CrossSection" | "Boundary" | "Structure" | "Observation" | "CRS";
  "entity_type": string;
  "entity_id"?: string | null;
  "message": string;
  "suggestion"?: string | null;
  "location"?: Record<string, unknown> | null;
  "context"?: Record<string, unknown>;
}

export interface QAThresholds {
  "maximum_projection_distance_m"?: number;
  "minimum_section_spacing_m"?: number;
  "maximum_section_spacing_m"?: number;
  "maximum_bed_jump_m"?: number;
  "maximum_reverse_bed_slope"?: number;
}

export interface RecommendationResponse {
  "task_id": number;
  "candidate": ParetoCandidateRecord | null;
  "execution_authorized"?: false;
  "notice"?: string;
}

export interface ReportGenerateRequest {
  "user"?: string;
  "context"?: AIContext;
}

export interface ReportGenerateResponse {
  "report_id": number;
  "title": string;
  "markdown_url": string;
  "pdf_url": string;
  "sources": Array<SourceCitation>;
  "execution_authorized"?: false;
  "notice": string;
  "created_time": string;
}

export interface ResultProductBundle {
  "max_envelope": Array<Record<string, unknown>>;
  "longitudinal_profile": Array<Record<string, unknown>>;
  "scenario_difference": Array<Record<string, unknown>>;
  "maximum_afflux": Record<string, unknown> | null;
  "afflux_reaches": Array<Record<string, unknown>>;
  "key_section_table": Array<Record<string, unknown>>;
  "calibration_table": Array<Record<string, unknown>>;
  "validation_table": Array<Record<string, unknown>>;
  "external_comparison_table": Array<Record<string, unknown>>;
  "geojson": Record<string, unknown>;
}

export interface ResultProductCommitRequest {
  "production_run_id": number;
  "product_code": string;
  "actor": string;
  "request": ResultProductRequest;
}

export interface ResultProductRecord {
  "id": number;
  "product_code": string;
  "production_run_id": number;
  "schema_version": string;
  "product_hash": string;
  "generated_at": string;
}

export interface ResultProductRequest {
  "project_id": string;
  "model_version": string;
  "baseline_scenario_id"?: string | null;
  "project_scenario_id": string;
  "afflux_threshold_m"?: number;
  "points": Array<HydraulicResultPoint>;
  "calibration_table"?: Array<Record<string, unknown>>;
  "validation_table"?: Array<Record<string, unknown>>;
  "external_comparison_table"?: Array<Record<string, unknown>>;
}

export interface ResultSectionOption {
  "section_id": number;
  "section_code": string;
  "branch_id": number;
  "chainage_m": number;
}

export interface RetireRequest {
  "retired_by": string;
  "reason": string;
}

export interface ReviewDecisionRequest {
  "reviewer": string;
  "decision": "approve" | "reject" | "request_changes";
  "comment"?: string | null;
}

export interface ReviewRecord {
  "id": number;
  "batch_id": number;
  "validation_run_id": number;
  "staging_content_hash": string;
  "reviewer": string;
  "decision": "approve" | "reject" | "request_changes";
  "comment"?: string | null;
  "created_at": string;
}

export interface ReviewSubmitRequest {
  "actor": string;
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

export interface RoughnessOverride {
  "group_id": string;
  "cross_section_ids": Array<number>;
  "manning_n": number;
}

export interface SimulationCaseCreate {
  "name": string;
  "description"?: string | null;
  "dataset_version_id": number;
  "boundary_condition_id": number;
  "boundary_condition_ids"?: Array<number>;
  "hydraulic_1d_configuration"?: Record<string, unknown> | null;
}

export interface SimulationCaseRecord {
  "name": string;
  "description"?: string | null;
  "dataset_version_id": number;
  "boundary_condition_id": number;
  "boundary_condition_ids"?: Array<number>;
  "hydraulic_1d_configuration"?: Record<string, unknown> | null;
  "id": number;
  "created_time": string;
}

export interface SimulationCaseUpdate {
  "name"?: string | null;
  "description"?: string | null;
  "boundary_condition_id"?: number | null;
  "boundary_condition_ids"?: Array<number> | null;
  "hydraulic_1d_configuration"?: Record<string, unknown> | null;
}

export interface SimulationLayerRecord {
  "id": number;
  "dataset_version_id": number;
  "task_id": number | null;
  "name": string;
  "layer_type": "water_level" | "velocity" | "flood_risk" | "terrain" | "facility_3d";
  "time_start": string | null;
  "time_end": string | null;
  "service_type": "COG" | "TITILER" | "MVT" | "WMS" | "3D_TILES";
  "service_url": string;
  "style": Record<string, unknown>;
  "version": string;
  "created_time": string;
}

export interface SimulationResultResponse {
  "task_id": number;
  "status": "pending" | "queued" | "running" | "cancel_requested" | "cancelled" | "success" | "failed";
  "simulation_id": string;
  "scenario_id": string;
  "engine": string;
  "engine_version": string;
  "section_id": number;
  "section_code": string;
  "branch_id": number;
  "chainage_m": number;
  "time": Array<number>;
  "water_level": Array<number>;
  "depth": Array<number | null>;
  "flow": Array<number>;
  "velocity": Array<number>;
  "flow_area": Array<number | null>;
  "wet_area": Array<number | null>;
  "hydraulic_radius": Array<number | null>;
  "top_width": Array<number | null>;
  "froude_number": Array<number | null>;
  "available_sections": Array<ResultSectionOption>;
  "diagnostics": Record<string, unknown> | null;
}

export interface SimulationTaskCreate {
  "case_id": number;
  "duration_seconds"?: number | null;
  "time_step_seconds"?: number | null;
  "output_interval_seconds"?: number | null;
  "initial_water_level"?: number | null;
  "initial_flow"?: number | null;
  "engine"?: "mascaret";
  "input_schema_version"?: "dayu.hydraulic-1d.input.v1";
  "storage_level"?: "full";
  "roughness_overrides"?: Array<RoughnessOverride>;
}

export interface SimulationTaskRecord {
  "id": number;
  "case_id": number;
  "dataset_version_id": number;
  "status": "pending" | "queued" | "running" | "cancel_requested" | "cancelled" | "success" | "failed";
  "progress": number;
  "config": Record<string, unknown>;
  "task_kind"?: "standard_1d" | "controlled_hydraulic_preview";
  "evidence_class"?: string | null;
  "input_schema_version": string | null;
  "input_snapshot_hash": string | null;
  "engine_version": string | null;
  "engine_commit": string | null;
  "solver_build_id": string | null;
  "build_mode": string | null;
  "build_verified": boolean;
  "solver_id": string | null;
  "capability_id": string | null;
  "runtime_adapter_id": string | null;
  "result_schema_version": string | null;
  "registry_hash": string | null;
  "execution_phase": string | null;
  "snapshot_summary"?: Record<string, unknown> | null;
  "queue_job_id": string | null;
  "delivery_attempt_count": number;
  "last_delivery_time": string | null;
  "worker_id": string | null;
  "queued_time": string | null;
  "heartbeat_time": string | null;
  "cancel_requested": boolean;
  "execution_attempt_count": number;
  "manual_retry_count": number;
  "infrastructure_retry_count": number;
  "retry_reason": string | null;
  "diagnostics": Record<string, unknown> | null;
  "result_path": string | null;
  "error_message": string | null;
  "last_infrastructure_error": string | null;
  "retry_eligible"?: boolean;
  "retry_block_reason"?: string | null;
  "created_time": string;
  "start_time": string | null;
  "end_time": string | null;
}

export interface SolverCapabilityRecord {
  "engine": string;
  "engine_version": string;
  "adapter_version": string;
  "feature": string;
  "status": string;
  "reason": string;
  "benchmark_ids": Array<string>;
  "verified_at": string | null;
}

export interface SourceCitation {
  "source_type": "knowledge" | "database" | "simulation" | "optimization";
  "title": string;
  "reference": string;
  "version": string;
  "updated_time"?: string | null;
  "excerpt"?: string | null;
}

export interface SpatialFeature {
  "object_type": "river" | "gate" | "pump" | "cross_section" | "hydrology_station";
  "object_id": number;
  "name": string;
  "geometry": Record<string, unknown>;
  "properties"?: Record<string, unknown>;
  "distance_m"?: number | null;
}

export interface SpatialSelectRequest {
  "dataset_version_id": number;
  "bbox": Array<number>;
  "object_types"?: Array<"river" | "gate" | "pump" | "cross_section">;
  "limit_per_type"?: number;
}

export interface SpatialSelectResponse {
  "dataset_version_id": number;
  "bbox": Array<number>;
  "features": Array<SpatialFeature>;
  "counts": Record<string, number>;
  "crs"?: "EPSG:4490";
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
  "solver_build_id": string | null;
  "build_mode": string | null;
  "build_verified": boolean;
  "snapshot": Record<string, unknown>;
}

export interface ThematicMapRequest {
  "dataset_version_id": number;
  "title"?: string;
  "time_seconds"?: number;
  "task_id"?: number | null;
  "dispatch_run_id"?: number | null;
  "bbox"?: Array<number> | null;
  "author"?: string;
}

export interface ThreeDTilesAsset {
  "layer_id": number;
  "name": string;
  "tileset_url": string;
  "version": string;
  "maximum_screen_space_error": number;
  "demo_data"?: true;
}

export interface TimeAlignmentOptions {
  "method"?: "exact" | "interpolation" | "nearest-with-tolerance";
  "tolerance_seconds"?: number;
  "minimum_valid_samples"?: number;
  "minimum_coverage_ratio"?: number;
}

export interface TimeSeriesImportPreview {
  "source_filename": string;
  "source_sha256": string;
  "row_count": number;
  "issues": Array<QAIssue>;
  "series": ProductionSeries;
  "provenance": Record<string, unknown>;
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

export interface TraceResponse {
  "dataset_version_id": number;
  "selected_river": SpatialFeature;
  "upstream_rivers": Array<SpatialFeature>;
  "downstream_rivers": Array<SpatialFeature>;
  "gates": Array<SpatialFeature>;
  "pumps": Array<SpatialFeature>;
  "cross_sections": Array<SpatialFeature>;
  "crs"?: "EPSG:4490";
}

export interface ValidationError {
  "loc": Array<string | number>;
  "msg": string;
  "type": string;
}

export interface ValidationIndependenceRequest {
  "calibration": DatasetWindow;
  "validation": DatasetWindow;
}

export interface ValidationIndependenceResult {
  "independent": boolean;
  "temporal_holdout": boolean;
  "issues": Array<QAIssue>;
}

export interface ValidationIssueRecord {
  "id": number;
  "validation_run_id": number;
  "batch_id": number;
  "entity_type": "river" | "cross_section" | "gate" | "pump";
  "feature_ref"?: string | null;
  "rule_code": string;
  "severity": "error" | "warning" | "info";
  "message": string;
  "geometry"?: Record<string, unknown> | null;
  "details_json": Record<string, unknown>;
  "created_at": string;
  "resolved_at"?: string | null;
  "resolution_note"?: string | null;
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

export interface ValidationRunCommitRequest {
  "validation_code": string;
  "production_run_id": number;
  "dataset_version_id": number;
  "case_id": number;
  "calibration_run_id"?: number | null;
  "actor": string;
  "calibration_dataset": DatasetWindow;
  "validation_dataset": DatasetWindow;
  "criteria": AcceptanceCriteria;
  "metric_evidence": Array<MetricEvidenceRequest>;
  "mass_balance_relative_error"?: number | null;
}

export interface ValidationSummary {
  "errors": number;
  "warnings": number;
  "passed": number;
  "is_model_ready": boolean;
}

export type ValidationReport = app__validation__schemas__ValidationReport;
export type DispatchValidationReport = app__dispatch__schemas__ValidationReport;
export type ValidationRunRecord = app__gis_governance__schemas__ValidationRunRecord;
export type ProductionValidationRunRecord = app__hydraulic__production__records__ValidationRunRecord;
export interface TimeSeriesImportOptions {
  series_kind: 'boundary' | 'observation';
  series_id: string;
  variable: 'water_level' | 'discharge';
  unit: 'm' | 'm3/s';
  source: string;
  branch_id: string;
  chainage_m: number;
  station_id?: string | null;
  vertical_datum?: string;
  time_basis: 'relative' | 'absolute';
  timezone?: string | null;
  column_mapping: { time: string; value: string; quality_flag?: string | null };
  sheet_name?: string | null;
}
export interface ExternalResultImportOptions {
  external_model_name: string;
  external_model_version?: string;
  scenario: string;
  vertical_datum: string;
  time_basis: 'relative' | 'absolute';
  timezone?: string | null;
  column_mapping: {
    branch: string; chainage: string; time: string;
    water_level?: string | null; discharge?: string | null; velocity?: string | null;
  };
  branch_mappings: Array<{
    external_branch: string; dayu_branch: string; chainage_scale?: number;
    chainage_offset_m?: number; direction?: 'same' | 'reverse';
    external_origin_m?: number; dayu_reference_end_m?: number | null;
  }>;
  sheet_name?: string | null;
}
export interface GISListQuery { dataset_version_id: number; bbox?: string; limit?: number; offset?: number; }
export interface GISFeatureInfoQuery { dataset_version_id: number; layer_key: string; bbox: string; width: number; height: number; x: number; y: number; }
export interface GISInteractionQuery { dataset_version_id: number; time_seconds?: number; task_id?: number; dispatch_run_id?: number; }
export interface GISAnnotationQuery { dataset_version_id: number; scale_denominator?: number; bbox?: string; annotation_type?: string; limit?: number; offset?: number; time_seconds?: number; task_id?: number; dispatch_run_id?: number; }
export interface GISLocationSearchQuery { dataset_version_id: number; q: string; limit?: number; }
export interface GISComparisonQuery { dataset_version_id: number; baseline_task_id: number; comparison_task_id: number; time_seconds?: number; baseline_dispatch_run_id?: number; comparison_dispatch_run_id?: number; }
export interface DGISStateQuery { dataset_version_id: number; feature_type?: string; feature_id?: number; time_start?: string; time_end?: string; bbox?: string; task_id?: number; limit?: number; offset?: number; }
export interface DGISReplayQuery { dataset_version_id: number; at: string; feature_type?: string; task_id?: number; }
export interface DGISLayerQuery { dataset_version_id: number; layer_type?: string; task_id?: number; }
export interface DatabaseListQuery { dataset_version_id?: number; river_id?: number; search?: string; limit?: number; offset?: number; }
export interface DatasetTaskListQuery { dataset_version_id?: number; }
export interface DispatchListQuery { dataset_version_id?: number; plan_id?: number; status?: string; limit?: number; offset?: number; }
export interface HydraulicExportQuery { dataset_version_id: number; network_id?: number; native?: boolean; }
export interface HydraulicStructureListQuery { dataset_version_id: number; network_id?: number; }
export interface HydraulicCoordinateOptions {
  source_crs: string;
  engineering_crs: string;
  coordinate_mode: 'geographic' | 'projected';
  axis_mapping: 'x_easting_y_northing' | 'x_northing_y_easting';
  horizontal_unit: 'm' | 'degree';
  vertical_datum: string;
  x_field?: string;
  y_field?: string;
  z_field?: string;
  vertical_unit?: 'm';
  central_meridian: number;
  zone_width: 3;
  zone_prefix_mode?: 'none' | 'included' | 'stripped';
}
export interface PageResult<T> { items: T[]; total: number; limit: number; offset: number; }
export type ImportResource = 'rivers' | 'cross_sections' | 'gates' | 'pumps';

export interface ApiErrorDetail {
  code: string;
  message: string;
  context?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly context?: Record<string, unknown>;

  constructor(status: number, detail?: string | ApiErrorDetail) {
    const fallback = `API 请求失败：${status}`;
    super(typeof detail === 'string' ? detail : detail?.message ?? fallback);
    this.name = 'ApiError';
    this.status = status;
    this.code = typeof detail === 'object' ? detail.code : undefined;
    this.context = typeof detail === 'object' ? detail.context : undefined;
  }
}

function isApiErrorDetail(value: unknown): value is ApiErrorDetail {
  if (typeof value !== 'object' || value === null) return false;
  const detail = value as Record<string, unknown>;
  return typeof detail.code === 'string'
    && typeof detail.message === 'string'
    && (detail.context === undefined || (
      typeof detail.context === 'object'
      && detail.context !== null
      && !Array.isArray(detail.context)
    ));
}

function decodeApiError(payload: unknown): string | ApiErrorDetail | undefined {
  if (typeof payload !== 'object' || payload === null || !('detail' in payload)) return undefined;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === 'string') return detail;
  return isApiErrorDetail(detail) ? detail : undefined;
}

function toQuery<T extends object>(params: T): string {
  const query = new URLSearchParams();
  Object.entries(params as Record<string, string | number | boolean | undefined>).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)); });
  const value = query.toString();
  return value ? `?${value}` : '';
}

function datasetTaskListArgs(
  paramsOrBaseUrl: DatasetTaskListQuery | string = {},
  baseUrl = '',
): [DatasetTaskListQuery, string] {
  return typeof paramsOrBaseUrl === 'string'
    ? [{}, paramsOrBaseUrl]
    : [paramsOrBaseUrl, baseUrl];
}

async function requestJson<T>(path: string, options: RequestInit = {}, baseUrl = ''): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, options);
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, decodeApiError(payload));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function requestBlob(path: string, options: RequestInit = {}, baseUrl = ''): Promise<Blob> {
  const response = await fetch(`${baseUrl}${path}`, options);
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, decodeApiError(payload));
  }
  return response.blob();
}

function jsonOptions(method: 'POST' | 'PUT' | 'PATCH', body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

export const getSystemInfo = (baseUrl = '') => requestJson<SystemInfoResponse>('/', {}, baseUrl);
export const getHealth = (baseUrl = '') => requestJson<HealthResponse>('/api/v1/health', {}, baseUrl);
export const getGISHealth = (baseUrl = '') => requestJson<GISHealthResponse>('/api/v1/gis/health', {}, baseUrl);
export const getGISStatistics = (datasetVersionId: number, baseUrl = '') => requestJson<GISStatisticsResponse>(`/api/v1/gis/stats${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getGeoServerHealth = (baseUrl = '') => requestJson<GeoServerHealthResponse>('/api/v1/gis/geoserver/health', {}, baseUrl);
export const getGeoServerLayers = (baseUrl = '') => requestJson<Array<GeoServerLayerRecord>>('/api/v1/gis/geoserver/layers', {}, baseUrl);
export const getGeoServerConfig = (baseUrl = '') => requestJson<GeoServerConfigResponse>('/api/v1/gis/geoserver/config', {}, baseUrl);
export const getGISCatalog = (datasetVersionId: number, baseUrl = '') => requestJson<GISCatalogResponse>(`/api/v1/gis/catalog${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getGISLayers = (datasetVersionId: number, baseUrl = '') => requestJson<Array<CatalogLayer>>(`/api/v1/gis/layers${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getGISFeatureInfo = (params: GISFeatureInfoQuery, baseUrl = '') => requestJson<GISFeatureInfoResponse>(`/api/v1/gis/feature-info${toQuery(params)}`, {}, baseUrl);
export const getGISBasemapTile = (basemapKey: string, z: number, y: number, x: number, baseUrl = '') => requestBlob(`/api/v1/gis/basemaps/${encodeURIComponent(basemapKey)}/tiles/${z}/${y}/${x}.jpeg`, {}, baseUrl);
export const getRivers = (params: GISListQuery, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/rivers${toQuery(params)}`, {}, baseUrl);
export const getRiver = (id: number, datasetVersionId: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/rivers/${id}${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getGates = (params: GISListQuery, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/gates${toQuery(params)}`, {}, baseUrl);
export const getGate = (id: number, datasetVersionId: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/gates/${id}${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getPumps = (params: GISListQuery, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/pumps${toQuery(params)}`, {}, baseUrl);
export const getPump = (id: number, datasetVersionId: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/pumps/${id}${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getCrossSections = (params: GISListQuery, baseUrl = '') => requestJson<GeoJSONFeatureCollection>(`/api/v1/gis/cross_sections${toQuery(params)}`, {}, baseUrl);
export const getCrossSection = (id: number, datasetVersionId: number, baseUrl = '') => requestJson<GeoJSONFeature>(`/api/v1/gis/cross_sections/${id}${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getGISInteractionFrame = (params: GISInteractionQuery, baseUrl = '') => requestJson<GISInteractionFrame>(`/api/v1/gis/interaction-frame${toQuery(params)}`, {}, baseUrl);
export const getGISLayerCatalog = (baseUrl = '') => requestJson<Array<LayerCatalogItem>>('/api/v1/gis-analysis/layers', {}, baseUrl);
export const searchGISLocations = (params: GISLocationSearchQuery, baseUrl = '') => requestJson<LocationSearchResponse>(`/api/v1/gis-analysis/search${toQuery(params)}`, {}, baseUrl);
export const getGISAnnotations = (params: GISAnnotationQuery, baseUrl = '') => requestJson<AnnotationCollection>(`/api/v1/gis-analysis/annotations${toQuery(params)}`, {}, baseUrl);
export const createGISAnnotation = (body: AnnotationCreate, baseUrl = '') => requestJson<AnnotationRecord>('/api/v1/gis-analysis/annotations', jsonOptions('POST', body), baseUrl);
export const updateGISAnnotation = (id: number, datasetVersionId: number, body: AnnotationUpdate, baseUrl = '') => requestJson<AnnotationRecord>(`/api/v1/gis-analysis/annotations/${id}${toQuery({ dataset_version_id: datasetVersionId })}`, jsonOptions('PUT', body), baseUrl);
export const deleteGISAnnotation = (id: number, datasetVersionId: number, baseUrl = '') => requestJson<void>(`/api/v1/gis-analysis/annotations/${id}${toQuery({ dataset_version_id: datasetVersionId })}`, { method: 'DELETE' }, baseUrl);
export const traceGISRiver = (datasetVersionId: number, riverId: number, baseUrl = '') => requestJson<TraceResponse>(`/api/v1/gis-analysis/trace${toQuery({ dataset_version_id: datasetVersionId, river_id: riverId })}`, {}, baseUrl);
export const selectGISFeatures = (body: SpatialSelectRequest, baseUrl = '') => requestJson<SpatialSelectResponse>('/api/v1/gis-analysis/select', jsonOptions('POST', body), baseUrl);
export const bufferGISFeatures = (body: BufferAnalysisRequest, baseUrl = '') => requestJson<BufferAnalysisResponse>('/api/v1/gis-analysis/buffer', jsonOptions('POST', body), baseUrl);
export const getNearestGISFacilities = (body: NearestFacilityRequest, baseUrl = '') => requestJson<NearestFacilityResponse>('/api/v1/gis-analysis/nearest', jsonOptions('POST', body), baseUrl);
export const getGISComparisonFrame = (params: GISComparisonQuery, baseUrl = '') => requestJson<GISComparisonFrame>(`/api/v1/gis-analysis/comparison-frame${toQuery(params)}`, {}, baseUrl);
export const downloadGISThematicMap = (body: ThematicMapRequest, baseUrl = '') => requestBlob('/api/v1/gis-analysis/thematic-map.pdf', jsonOptions('POST', body), baseUrl);
export const getGISVectorTile = (layer: 'river' | 'gate' | 'pump' | 'cross_section' | 'map_annotation', z: number, x: number, y: number, datasetVersionId: number, baseUrl = '') => requestBlob(`/api/v1/gis-analysis/vector-tiles/${layer}/${z}/${x}/${y}.mvt${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);

export const getDGISHealth = (baseUrl = '') => requestJson<DGISHealthResponse>('/api/v1/dgis/health', {}, baseUrl);
export const getDGISCatalog = (datasetVersionId: number, baseUrl = '') => requestJson<DGISCatalogResponse>(`/api/v1/dgis/catalog${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getDGISFeatureStates = (params: DGISStateQuery, baseUrl = '') => requestJson<FeatureStateCollection>(`/api/v1/dgis/feature-states${toQuery(params)}`, {}, baseUrl);
export const createDGISFeatureState = (body: FeatureStateCreate, baseUrl = '') => requestJson<FeatureStateRecord>('/api/v1/dgis/feature-states', jsonOptions('POST', body), baseUrl);
export const replayDGISFeatureStates = (params: DGISReplayQuery, baseUrl = '') => requestJson<FeatureStateCollection>(`/api/v1/dgis/feature-states/replay${toQuery(params)}`, {}, baseUrl);
export const getDGISSimulationLayers = (params: DGISLayerQuery, baseUrl = '') => requestJson<Array<SimulationLayerRecord>>(`/api/v1/dgis/simulation-layers${toQuery(params)}`, {}, baseUrl);
export const getDGISThreeDTiles = (datasetVersionId: number, baseUrl = '') => requestJson<Array<ThreeDTilesAsset>>(`/api/v1/dgis/3d-tiles${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getDGISConversionCapabilities = (baseUrl = '') => requestJson<ConversionCapabilityResponse>('/api/v1/dgis/conversions/capabilities', {}, baseUrl);

async function uploadDGISConversion(path: 'inspect' | 'geojson' | 'cog' | 'postgis', file: File, fields: Record<string, string | number> = {}, baseUrl = ''): Promise<ConversionJobResponse> {
  const body = new FormData();
  body.set('file', file);
  Object.entries(fields).forEach(([key, value]) => body.set(key, String(value)));
  return requestJson<ConversionJobResponse>(`/api/v1/dgis/conversions/${path}`, { method: 'POST', body }, baseUrl);
}

export const inspectDGISFile = (file: File, baseUrl = '') => uploadDGISConversion('inspect', file, {}, baseUrl);
export const convertDGISToGeoJSON = (file: File, targetSrid = 4490, baseUrl = '') => uploadDGISConversion('geojson', file, { target_srid: targetSrid }, baseUrl);
export const convertDGISToCOG = (file: File, targetSrid = 4490, baseUrl = '') => uploadDGISConversion('cog', file, { target_srid: targetSrid }, baseUrl);
export type DGISGovernedEntityType = NonNullable<
  Body_import_to_postgis_api_v1_dgis_conversions_postgis_post['entity_type']
>;

export interface DGISPostGISImportOptions {
  targetSrid?: number;
  entityType?: DGISGovernedEntityType;
  parentVersionId?: number;
  operator?: string;
  baseUrl?: string;
}

/** Import a raw file with explicit governance provenance while retaining the legacy call signature. */
export function importDGISToPostGIS(
  file: File,
  layerName: string,
  options?: DGISPostGISImportOptions,
): Promise<ConversionJobResponse>;
export function importDGISToPostGIS(
  file: File,
  layerName: string,
  targetSrid?: number,
  baseUrl?: string,
): Promise<ConversionJobResponse>;
export function importDGISToPostGIS(
  file: File,
  layerName: string,
  optionsOrTargetSrid?: DGISPostGISImportOptions | number,
  legacyBaseUrl = '',
): Promise<ConversionJobResponse> {
  const options: DGISPostGISImportOptions = typeof optionsOrTargetSrid === 'number'
    ? { targetSrid: optionsOrTargetSrid, baseUrl: legacyBaseUrl }
    : optionsOrTargetSrid ?? { baseUrl: legacyBaseUrl };
  const fields: Record<string, string | number> = {
    layer_name: layerName,
    target_srid: options.targetSrid ?? 4490,
  };
  if (options.entityType !== undefined) fields.entity_type = options.entityType;
  if (options.parentVersionId !== undefined) fields.parent_version_id = options.parentVersionId;
  if (options.operator !== undefined) fields.operator = options.operator;
  return uploadDGISConversion('postgis', file, fields, options.baseUrl ?? '');
}

export const createGISGovernanceBatch = (body: BatchCreate, baseUrl = '') => requestJson<BatchRecord>('/api/v1/gis-governance/batches', jsonOptions('POST', body), baseUrl);
export const listGISGovernanceBatches = (baseUrl = '') => requestJson<Array<BatchRecord>>('/api/v1/gis-governance/batches', {}, baseUrl);
export const getGISGovernanceBatch = (batchId: number, baseUrl = '') => requestJson<BatchRecord>(`/api/v1/gis-governance/batches/${batchId}`, {}, baseUrl);
export const stageGISGovernanceBatch = (batchId: number, body: BatchStageRequest, baseUrl = '') => requestJson<BatchRecord>(`/api/v1/gis-governance/batches/${batchId}/stage`, jsonOptions('POST', body), baseUrl);
export const validateGISGovernanceBatch = (batchId: number, baseUrl = '') => requestJson<ValidationRunRecord>(`/api/v1/gis-governance/batches/${batchId}/validate`, { method: 'POST' }, baseUrl);
export const getGISGovernanceValidation = (batchId: number, baseUrl = '') => requestJson<ValidationRunRecord>(`/api/v1/gis-governance/batches/${batchId}/validation`, {}, baseUrl);
export const listGISGovernanceIssues = (batchId: number, baseUrl = '') => requestJson<Array<ValidationIssueRecord>>(`/api/v1/gis-governance/batches/${batchId}/issues`, {}, baseUrl);
export const submitGISGovernanceReview = (batchId: number, body: ReviewSubmitRequest, baseUrl = '') => requestJson<BatchRecord>(`/api/v1/gis-governance/batches/${batchId}/submit-review`, jsonOptions('POST', body), baseUrl);
export const reviewGISGovernanceBatch = (batchId: number, body: ReviewDecisionRequest, baseUrl = '') => requestJson<ReviewRecord>(`/api/v1/gis-governance/batches/${batchId}/review`, jsonOptions('POST', body), baseUrl);
export const getGISGovernanceDiff = (batchId: number, baseUrl = '') => requestJson<BatchDiff>(`/api/v1/gis-governance/batches/${batchId}/diff`, {}, baseUrl);
export const promoteGISGovernanceBatch = (batchId: number, body: PromoteRequest, baseUrl = '') => requestJson<PromotedVersionRecord>(`/api/v1/gis-governance/batches/${batchId}/promote`, jsonOptions('POST', body), baseUrl);
export const listGISGovernancePublications = (baseUrl = '') => requestJson<Array<PublicationRecord>>('/api/v1/gis-governance/publications', {}, baseUrl);
export const publishGISGovernanceVersion = (versionId: number, body: PublishRequest, baseUrl = '') => requestJson<PublicationRecord>(`/api/v1/gis-governance/versions/${versionId}/publish`, jsonOptions('POST', body), baseUrl);
export const retireGISGovernanceVersion = (versionId: number, body: RetireRequest, baseUrl = '') => requestJson<PromotedVersionRecord>(`/api/v1/gis-governance/versions/${versionId}/retire`, jsonOptions('POST', body), baseUrl);

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
export const createDatasetVersion = (body: DatasetVersionCreate, baseUrl = '') => requestJson<DatasetVersionRecord>('/api/v1/model-data/dataset-versions', jsonOptions('POST', body), baseUrl);
export const updateDatasetVersion = (versionId: number, body: DatasetVersionUpdate, baseUrl = '') => requestJson<DatasetVersionRecord>(`/api/v1/model-data/dataset-versions/${versionId}`, jsonOptions('PUT', body), baseUrl);
export const deleteDatasetVersion = (versionId: number, baseUrl = '') => requestJson<void>(`/api/v1/model-data/dataset-versions/${versionId}`, { method: 'DELETE' }, baseUrl);
export const getModelParameters = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<ModelParameterRecord>>(`/api/v1/model-data/parameters${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const createModelParameter = (body: ModelParameterCreate, baseUrl = '') => requestJson<ModelParameterRecord>('/api/v1/model-data/parameters', jsonOptions('POST', body), baseUrl);
export const updateModelParameter = (parameterId: number, body: ModelParameterUpdate, baseUrl = '') => requestJson<ModelParameterRecord>(`/api/v1/model-data/parameters/${parameterId}`, jsonOptions('PUT', body), baseUrl);
export const deleteModelParameter = (parameterId: number, baseUrl = '') => requestJson<void>(`/api/v1/model-data/parameters/${parameterId}`, { method: 'DELETE' }, baseUrl);
export const getBoundaryConditions = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<BoundaryConditionRecord>>(`/api/v1/model-data/boundary-conditions${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const createBoundaryCondition = (body: BoundaryConditionCreate, baseUrl = '') => requestJson<BoundaryConditionRecord>('/api/v1/model-data/boundary-conditions', jsonOptions('POST', body), baseUrl);
export const updateBoundaryCondition = (boundaryId: number, body: BoundaryConditionUpdate, baseUrl = '') => requestJson<BoundaryConditionRecord>(`/api/v1/model-data/boundary-conditions/${boundaryId}`, jsonOptions('PUT', body), baseUrl);
export const deleteBoundaryCondition = (boundaryId: number, baseUrl = '') => requestJson<void>(`/api/v1/model-data/boundary-conditions/${boundaryId}`, { method: 'DELETE' }, baseUrl);
export const getSimulationCases = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<SimulationCaseRecord>>(`/api/v1/model-data/simulation-cases${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const createSimulationCase = (body: SimulationCaseCreate, baseUrl = '') => requestJson<SimulationCaseRecord>('/api/v1/model-data/simulation-cases', jsonOptions('POST', body), baseUrl);
export const updateSimulationCase = (caseId: number, body: SimulationCaseUpdate, baseUrl = '') => requestJson<SimulationCaseRecord>(`/api/v1/model-data/simulation-cases/${caseId}`, jsonOptions('PUT', body), baseUrl);
export const deleteSimulationCase = (caseId: number, baseUrl = '') => requestJson<void>(`/api/v1/model-data/simulation-cases/${caseId}`, { method: 'DELETE' }, baseUrl);
export const runValidation = (datasetVersionId: number, baseUrl = '') => requestJson<ValidationReport>('/api/v1/validation/run', jsonOptions('POST', { dataset_version_id: datasetVersionId }), baseUrl);

export const getHydraulicCapabilities = (baseUrl = '') => requestJson<HydraulicCapabilityResponse>('/api/v1/hydraulic/capabilities', {}, baseUrl);
export const getHydraulicEngineCapabilities = (baseUrl = '') => requestJson<Array<SolverCapabilityRecord>>('/api/v1/hydraulic/engine-capabilities', {}, baseUrl);
export const getHydraulicNetworkGraph = (networkId: number, baseUrl = '') => requestJson<HydraulicNetworkGraphRecord>(`/api/v1/hydraulic/networks/${networkId}/graph`, {}, baseUrl);
export const listHydraulicStructures = (params: HydraulicStructureListQuery, baseUrl = '') => requestJson<Array<HydraulicStructureRecord>>(`/api/v1/hydraulic/structures${toQuery(params)}`, {}, baseUrl);
export const getHydraulicStructure = (structureId: number, baseUrl = '') => requestJson<HydraulicStructureRecord>(`/api/v1/hydraulic/structures/${structureId}`, {}, baseUrl);
export const createHydraulicStructure = (body: HydraulicStructureCreate, baseUrl = '') => requestJson<HydraulicStructureRecord>('/api/v1/hydraulic/structures', jsonOptions('POST', body), baseUrl);
export const updateHydraulicStructure = (structureId: number, body: HydraulicStructureUpdate, baseUrl = '') => requestJson<HydraulicStructureRecord>(`/api/v1/hydraulic/structures/${structureId}`, jsonOptions('PUT', body), baseUrl);
export const deleteHydraulicStructure = (structureId: number, baseUrl = '') => requestJson<void>(`/api/v1/hydraulic/structures/${structureId}`, { method: 'DELETE' }, baseUrl);
export const upsertHydraulicStructureScenario = (structureId: number, caseId: number, body: HydraulicStructureScenarioUpsert, baseUrl = '') => requestJson<HydraulicStructureScenarioRecord>(`/api/v1/hydraulic/structures/${structureId}/scenarios/${caseId}`, jsonOptions('PUT', body), baseUrl);
export const listHydraulicNetworks = (datasetVersionId: number, baseUrl = '') => requestJson<Array<HydraulicNetworkRecord>>(`/api/v1/hydraulic/networks${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const getHydraulicSection = (sectionId: number, baseUrl = '') => requestJson<HydraulicSectionDetail>(`/api/v1/hydraulic/cross-sections/${sectionId}`, {}, baseUrl);
export const listHydraulicImportJobs = (datasetVersionId: number, baseUrl = '') => requestJson<Array<HydraulicImportJobRecord>>(`/api/v1/hydraulic/imports${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const commitHydraulicImport = (jobCode: string, previewConfigHash: string, baseUrl = '') => requestJson<HydraulicImportJobRecord>('/api/v1/hydraulic/imports/commit', jsonOptions('POST', { job_code: jobCode, preview_config_hash: previewConfigHash }), baseUrl);
export const buildHydraulicTopology = (networkId: number, body: HydraulicTopologyBuildRequest, baseUrl = '') => requestJson<HydraulicTopologyReport>(`/api/v1/hydraulic/networks/${networkId}/topology`, jsonOptions('POST', body), baseUrl);
export const reverseHydraulicBranch = (branchId: number, baseUrl = '') => requestJson<HydraulicBranchActionRecord>(`/api/v1/hydraulic/branches/${branchId}/reverse`, { method: 'POST' }, baseUrl);
export const recalculateHydraulicBranchChainage = (branchId: number, baseUrl = '') => requestJson<HydraulicBranchActionRecord>(`/api/v1/hydraulic/branches/${branchId}/recalculate-chainage`, { method: 'POST' }, baseUrl);
export const locateHydraulicSection = (sectionId: number, body: HydraulicLocateRequest, baseUrl = '') => requestJson<HydraulicSectionDetail>(`/api/v1/hydraulic/cross-sections/${sectionId}/locate`, jsonOptions('POST', body), baseUrl);
export const processHydraulicProfile = (profileId: number, body: HydraulicProcessRequest, baseUrl = '') => requestJson<HydraulicProcessingRecord>(`/api/v1/hydraulic/profiles/${profileId}/process`, jsonOptions('POST', body), baseUrl);
export const batchProcessHydraulicProfiles = (body: HydraulicBatchProcessRequest, baseUrl = '') => requestJson<Array<HydraulicProcessingRecord>>('/api/v1/hydraulic/profiles/process-batch', jsonOptions('POST', body), baseUrl);
export const runHydraulicDataValidation = (datasetVersionId: number, baseUrl = '') => requestJson<HydraulicValidationRunRecord>('/api/v1/hydraulic/validation/run', jsonOptions('POST', { dataset_version_id: datasetVersionId }), baseUrl);
export const getHydraulicDataValidation = (runCode: string, baseUrl = '') => requestJson<HydraulicValidationRunRecord>(`/api/v1/hydraulic/validation/${encodeURIComponent(runCode)}`, {}, baseUrl);
export const downloadHydraulicNetwork = (params: HydraulicExportQuery, baseUrl = '') => requestBlob(`/api/v1/hydraulic/exports/network.nwk11${toQuery({ dataset_version_id: params.dataset_version_id, network_id: params.network_id })}`, {}, baseUrl);
export const downloadHydraulicSections = (params: HydraulicExportQuery, baseUrl = '') => requestBlob(`/api/v1/hydraulic/exports/cross-sections.xns11${toQuery(params)}`, {}, baseUrl);
export const downloadHydraulicTemplate = (name: 'river-network' | 'cross-section', baseUrl = '') => requestBlob(`/api/v1/hydraulic/templates/${name}`, {}, baseUrl);

export async function previewHydraulicImport(datasetVersionId: number, options: HydraulicCoordinateOptions, file: File, baseUrl = ''): Promise<HydraulicImportPreview> {
  const body = new FormData();
  body.set('dataset_version_id', String(datasetVersionId));
  Object.entries(options).forEach(([key, value]) => {
    if (value !== undefined && value !== '') body.set(key, String(value));
  });
  body.set('file', file);
  return requestJson<HydraulicImportPreview>('/api/v1/hydraulic/imports/preview', { method: 'POST', body }, baseUrl);
}

export const getProductionCapabilities = (baseUrl = '') => requestJson<ProductionCapabilityResponse>('/api/v1/hydraulic/production/capabilities', {}, baseUrl);
export const createProductionRun = (body: ProductionTaskCreateRequest, baseUrl = '') => requestJson<ProductionRunRecord>('/api/v1/hydraulic/production/runs', jsonOptions('POST', body), baseUrl);
export const listProductionRuns = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<ProductionRunRecord>>(`/api/v1/hydraulic/production/runs${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const listProductionAudit = (datasetVersionId?: number, baseUrl = '') => requestJson<Array<AuditEventRecord>>(`/api/v1/hydraulic/production/audit${toQuery({ dataset_version_id: datasetVersionId })}`, {}, baseUrl);
export const approveProductionRun = (runId: number, body: ProductionApprovalRequest, baseUrl = '') => requestJson<ProductionRunRecord>(`/api/v1/hydraulic/production/runs/${runId}/approve`, jsonOptions('POST', body), baseUrl);
export const evaluateProductionQA = (body: HydraulicModelQARequest, baseUrl = '') => requestJson<HydraulicModelQAResult>('/api/v1/hydraulic/production/qa/evaluate', jsonOptions('POST', body), baseUrl);
export const evaluateProductionMetrics = (body: MetricEvaluationRequest, baseUrl = '') => requestJson<HydraulicMetrics>('/api/v1/hydraulic/production/metrics/evaluate', jsonOptions('POST', body), baseUrl);
export const planProductionCalibration = (body: ParameterSweepRequest, baseUrl = '') => requestJson<ParameterSweepPlan>('/api/v1/hydraulic/production/calibration/sweeps/plan', jsonOptions('POST', body), baseUrl);
export const createProductionCalibrationSweep = (body: CalibrationSweepCreateRequest, baseUrl = '') => requestJson<CalibrationSweepRunResponse>('/api/v1/hydraulic/production/calibration/sweeps/create', jsonOptions('POST', body), baseUrl);
export const commitProductionCalibrationRun = (body: CalibrationRunCommitRequest, baseUrl = '') => requestJson<CalibrationRunRecord>('/api/v1/hydraulic/production/calibration/runs', jsonOptions('POST', body), baseUrl);
export const rankProductionCalibration = (body: CalibrationRankingRequest, baseUrl = '') => requestJson<Array<CalibrationCandidate>>('/api/v1/hydraulic/production/calibration/candidates/rank', jsonOptions('POST', body), baseUrl);
export const promoteProductionCalibration = (calibrationRunId: number, body: CalibrationPromotionRequest, baseUrl = '') => requestJson<CalibrationPromotionResponse>(`/api/v1/hydraulic/production/calibration/runs/${calibrationRunId}/accept`, jsonOptions('POST', body), baseUrl);
export const evaluateProductionIndependence = (body: ValidationIndependenceRequest, baseUrl = '') => requestJson<ValidationIndependenceResult>('/api/v1/hydraulic/production/validation/independence', jsonOptions('POST', body), baseUrl);
export const evaluateProductionAcceptance = (body: AcceptanceEvaluationRequest, baseUrl = '') => requestJson<AcceptanceEvaluation>('/api/v1/hydraulic/production/validation/acceptance', jsonOptions('POST', body), baseUrl);
export const commitProductionValidationRun = (body: ValidationRunCommitRequest, baseUrl = '') => requestJson<ProductionValidationRunRecord>('/api/v1/hydraulic/production/validation/runs', jsonOptions('POST', body), baseUrl);
export const compareProductionExternal = (body: ExternalComparisonRequest, baseUrl = '') => requestJson<ExternalComparisonResult>('/api/v1/hydraulic/production/external-results/compare', jsonOptions('POST', body), baseUrl);
export const generateProductionProducts = (body: ResultProductRequest, baseUrl = '') => requestJson<ResultProductBundle>('/api/v1/hydraulic/production/products/generate', jsonOptions('POST', body), baseUrl);
export const commitProductionProduct = (body: ResultProductCommitRequest, baseUrl = '') => requestJson<ResultProductRecord>('/api/v1/hydraulic/production/products/commit', jsonOptions('POST', body), baseUrl);
export const exportProductionProductsCsv = (body: ResultProductRequest, baseUrl = '') => requestBlob('/api/v1/hydraulic/production/products/export.csv', jsonOptions('POST', body), baseUrl);
export const exportProductionProductsXlsx = (body: ResultProductRequest, baseUrl = '') => requestBlob('/api/v1/hydraulic/production/products/export.xlsx', jsonOptions('POST', body), baseUrl);
export const exportProductionProductsGeojson = (body: ResultProductRequest, baseUrl = '') => requestBlob('/api/v1/hydraulic/production/products/export.geojson', jsonOptions('POST', body), baseUrl);
export const buildProductionAcceptanceManifest = (body: AcceptanceManifestRequest, baseUrl = '') => requestJson<AcceptanceManifest>('/api/v1/hydraulic/production/acceptance-manifest', jsonOptions('POST', body), baseUrl);

export async function previewProductionSeries(options: TimeSeriesImportOptions, file: File, baseUrl = ''): Promise<TimeSeriesImportPreview> {
  const body = new FormData();
  body.set('options_json', JSON.stringify(options));
  body.set('file', file);
  return requestJson<TimeSeriesImportPreview>('/api/v1/hydraulic/production/time-series/preview', { method: 'POST', body }, baseUrl);
}

export async function importProductionObservation(datasetVersionId: number, actor: string, options: TimeSeriesImportOptions, file: File, baseUrl = ''): Promise<ObservationRecord> {
  const body = new FormData();
  body.set('dataset_version_id', String(datasetVersionId));
  body.set('actor', actor);
  body.set('options_json', JSON.stringify(options));
  body.set('file', file);
  return requestJson<ObservationRecord>('/api/v1/hydraulic/production/observations/import', { method: 'POST', body }, baseUrl);
}

export async function previewProductionExternal(options: ExternalResultImportOptions, file: File, baseUrl = ''): Promise<ExternalResultPreview> {
  const body = new FormData();
  body.set('options_json', JSON.stringify(options));
  body.set('file', file);
  return requestJson<ExternalResultPreview>('/api/v1/hydraulic/production/external-results/preview', { method: 'POST', body }, baseUrl);
}

export async function importProductionExternal(datasetVersionId: number, resultCode: string, actor: string, options: ExternalResultImportOptions, file: File, baseUrl = ''): Promise<ExternalResultRecord> {
  const body = new FormData();
  body.set('dataset_version_id', String(datasetVersionId));
  body.set('result_code', resultCode);
  body.set('actor', actor);
  body.set('options_json', JSON.stringify(options));
  body.set('file', file);
  return requestJson<ExternalResultRecord>('/api/v1/hydraulic/production/external-results/import', { method: 'POST', body }, baseUrl);
}

export const createHydraulicTask = (body: SimulationTaskCreate, baseUrl = '') => requestJson<SimulationTaskRecord>('/api/v1/model/tasks', jsonOptions('POST', body), baseUrl);
export const getHydraulicReadiness = (caseId: number, baseUrl = '') => requestJson<Hydraulic1DReadinessResponse>(`/api/v1/model/readiness${toQuery({ case_id: caseId })}`, {}, baseUrl);
export const previewHydraulicModel = (body: SimulationTaskCreate, baseUrl = '') => requestJson<Hydraulic1DPreviewResponse>('/api/v1/model/preview', jsonOptions('POST', body), baseUrl);
export const listHydraulicTasks = (paramsOrBaseUrl: DatasetTaskListQuery | string = {}, baseUrl = '') => {
  const [params, resolvedBaseUrl] = datasetTaskListArgs(paramsOrBaseUrl, baseUrl);
  return requestJson<Array<SimulationTaskRecord>>(`/api/v1/model/tasks${toQuery(params)}`, {}, resolvedBaseUrl);
};
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
export const cloneDispatchPlanForHydraulic = (planId: number, baseUrl = '') => requestJson<DispatchPlanRecord>(`/api/v1/dispatch/plans/${planId}/hydraulic-clone`, { method: 'POST' }, baseUrl);
export const validateDispatchPlan = (planId: number, baseUrl = '') => requestJson<DispatchValidationReport>(`/api/v1/dispatch/plans/${planId}/validate`, { method: 'POST' }, baseUrl);
export const freezeDispatchPlan = (planId: number, baseUrl = '') => requestJson<DispatchPlanRecord>(`/api/v1/dispatch/plans/${planId}/freeze`, { method: 'POST' }, baseUrl);
export const getDispatchExecutionReadiness = (planId: number, baseUrl = '') => requestJson<DispatchExecutionReadiness>(`/api/v1/dispatch/plans/${planId}/readiness`, {}, baseUrl);
export const previewDispatchSchedule = (planId: number, body: DispatchSchedulePreviewRequest, baseUrl = '') => requestJson<DispatchSchedulePreview>(`/api/v1/dispatch/plans/${planId}/schedule-preview`, jsonOptions('POST', body), baseUrl);
export const compileDispatchHydraulicPlan = (planId: number, body: HydraulicPlanCompileRequest, baseUrl = '') => requestJson<HydraulicPlanCompileReport>(`/api/v1/dispatch/plans/${planId}/hydraulic-compile-check`, jsonOptions('POST', body), baseUrl);
export const freezeDispatchHydraulicPlan = (planId: number, body: HydraulicPlanCompileRequest, baseUrl = '') => requestJson<HydraulicPlanFreezeResponse>(`/api/v1/dispatch/plans/${planId}/hydraulic-freeze`, jsonOptions('POST', body), baseUrl);
export const previewDispatchHydraulicPlan = (planId: number, body: HydraulicPlanCompileRequest, baseUrl = '') => requestJson<HydraulicPreviewJobRecord>(`/api/v1/dispatch/plans/${planId}/hydraulic-preview`, jsonOptions('POST', body), baseUrl);
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
export const listOptimizationTasks = (paramsOrBaseUrl: DatasetTaskListQuery | string = {}, baseUrl = '') => {
  const [params, resolvedBaseUrl] = datasetTaskListArgs(paramsOrBaseUrl, baseUrl);
  return requestJson<Array<OptimizationTaskRecord>>(`/api/v1/optimization/tasks${toQuery(params)}`, {}, resolvedBaseUrl);
};
export const getOptimizationTask = (taskId: number, baseUrl = '') => requestJson<OptimizationTaskRecord>(`/api/v1/optimization/tasks/${taskId}`, {}, baseUrl);
export const runOptimizationTask = (taskId: number, baseUrl = '') => requestJson<OptimizationTaskRecord>(`/api/v1/optimization/tasks/${taskId}/run`, { method: 'POST' }, baseUrl);
export const cancelOptimizationTask = (taskId: number, baseUrl = '') => requestJson<OptimizationTaskRecord>(`/api/v1/optimization/tasks/${taskId}/cancel`, { method: 'POST' }, baseUrl);
export const getOptimizationCandidates = (taskId: number, baseUrl = '') => requestJson<Array<OptimizationCandidateRecord>>(`/api/v1/optimization/tasks/${taskId}/candidates`, {}, baseUrl);
export const getOptimizationPareto = (taskId: number, baseUrl = '') => requestJson<Array<ParetoCandidateRecord>>(`/api/v1/optimization/tasks/${taskId}/pareto`, {}, baseUrl);
export const getOptimizationRecommendation = (taskId: number, baseUrl = '') => requestJson<RecommendationResponse>(`/api/v1/optimization/tasks/${taskId}/recommendation`, {}, baseUrl);
export const explainOptimizationRecommendation = (taskId: number, baseUrl = '') => requestJson<OptimizationExplanation>(`/api/v1/optimization/tasks/${taskId}/explain`, {}, baseUrl);

export const chatWithAI = (body: AIChatRequest, baseUrl = '') => requestJson<AIChatResponse>('/api/v1/ai/chat', jsonOptions('POST', body), baseUrl);
export const searchAIKnowledge = (query: string, limit = 5, baseUrl = '') => requestJson<KnowledgeSearchResponse>(`/api/v1/ai/knowledge/search${toQuery({ q: query, limit })}`, {}, baseUrl);
export const listAIKnowledgeDocuments = (baseUrl = '') => requestJson<Array<KnowledgeDocumentRecord>>('/api/v1/ai/knowledge/documents', {}, baseUrl);
export const generateAIReport = (body: ReportGenerateRequest, baseUrl = '') => requestJson<ReportGenerateResponse>('/api/v1/ai/report/generate', jsonOptions('POST', body), baseUrl);
export const listAIToolLogs = (limit = 20, offset = 0, baseUrl = '') => requestJson<Array<AIToolCallLogRecord>>(`/api/v1/ai/tools/logs${toQuery({ limit, offset })}`, {}, baseUrl);

export async function uploadAIKnowledgeDocument(file: File, category: string, version: string, baseUrl = ''): Promise<KnowledgeDocumentRecord> {
  const body = new FormData();
  body.set('file', file);
  body.set('category', category);
  body.set('version', version);
  return requestJson<KnowledgeDocumentRecord>('/api/v1/ai/knowledge/documents', { method: 'POST', body }, baseUrl);
}

export async function uploadDataFile(kind: 'excel' | 'csv' | 'geojson', resource: ImportResource, datasetVersionId: number, file: File, baseUrl = ''): Promise<ImportResponse> {
  const body = new FormData();
  body.set('resource', resource);
  body.set('dataset_version_id', String(datasetVersionId));
  body.set('file', file);
  return requestJson<ImportResponse>(`/api/v1/import/${kind}`, { method: 'POST', body }, baseUrl);
}
