import { getCrossSection, getGate, getPump, getRiver, type GeoJSONFeature } from '../../api/generated/client';

export interface FeatureIdentity {
  layerKey: string;
  featureId: number;
  datasetVersionId: number;
}

export function parseFeatureIdentity(raw: string | undefined, datasetVersionId: number): FeatureIdentity | null {
  if (!raw) return null;
  const separator = raw.lastIndexOf(':');
  const layerKey = raw.slice(0, separator);
  const featureId = Number(raw.slice(separator + 1));
  if (separator <= 0 || !/^[a-z][a-z0-9_]{1,62}$/.test(layerKey) || !Number.isSafeInteger(featureId) || featureId <= 0) return null;
  return { layerKey, featureId, datasetVersionId };
}

const detailReaders: Record<string, (id: number, version: number) => Promise<GeoJSONFeature>> = {
  river_detail: getRiver,
  gate_detail: getGate,
  pump_detail: getPump,
  cross_section_detail: getCrossSection,
};

export async function readFeatureDetail(identity: FeatureIdentity, detailRouteKey: string | null): Promise<Record<string, unknown>> {
  const reader = detailRouteKey ? detailReaders[detailRouteKey] : undefined;
  if (!reader) return { id: identity.featureId, layer_key: identity.layerKey, dataset_version_id: identity.datasetVersionId };
  const feature = await reader(identity.featureId, identity.datasetVersionId);
  return feature.properties;
}
