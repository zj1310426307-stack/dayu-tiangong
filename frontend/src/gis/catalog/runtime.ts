import type { CatalogGroup, CatalogLayer, CatalogService, GISCatalogResponse } from '../../api/generated/client';

export type CatalogMode = 'legacy' | 'shadow' | 'catalog';

export interface LayerRuntime {
  key: string;
  title: string;
  groupKey: string;
  groupTitle: string;
  order: number;
  datasetVersionId: number;
  serviceMode: CatalogLayer['service_mode'];
  renderMode: CatalogLayer['render_mode'];
  service: CatalogService;
  descriptor: CatalogLayer;
  visible: boolean;
  opacity: number;
}

export interface CatalogRuntime {
  revision: string;
  groups: CatalogGroup[];
  layers: LayerRuntime[];
  catalog: GISCatalogResponse;
}

/** Validate cross-references and normalize only the frozen v1alpha1 contract. */
export function normalizeCatalog(catalog: GISCatalogResponse): CatalogRuntime {
  if (catalog.schema_version !== 'gis-catalog/v1alpha1') {
    throw new Error(`CATALOG_SCHEMA_UNSUPPORTED: ${catalog.schema_version}`);
  }
  const services = new Map(catalog.services.map((service) => [service.service_key, service]));
  const groups = new Set(catalog.groups.map((group) => group.group_key));
  const seen = new Set<string>();
  const layers = catalog.layers.map((layer): LayerRuntime => {
    if (seen.has(layer.key)) throw new Error(`CATALOG_LAYER_DUPLICATE: ${layer.key}`);
    seen.add(layer.key);
    const service = services.get(layer.service_key);
    if (!service || service.service_mode !== layer.service_mode) {
      throw new Error(`CATALOG_SERVICE_MISMATCH: ${layer.key}`);
    }
    if (!groups.has(layer.group_key)) throw new Error(`CATALOG_GROUP_MISSING: ${layer.key}`);
    if (layer.dataset_version_id !== catalog.dataset.dataset_version_id) {
      throw new Error(`CATALOG_VERSION_MISMATCH: ${layer.key}`);
    }
    return {
      key: layer.key,
      title: layer.display_title || layer.title,
      groupKey: layer.group_key,
      groupTitle: layer.group_title,
      order: layer.order,
      datasetVersionId: layer.dataset_version_id,
      serviceMode: layer.service_mode,
      renderMode: layer.render_mode,
      service,
      descriptor: layer,
      visible: layer.default_visible,
      opacity: layer.default_opacity,
    };
  });
  return { revision: catalog.catalog_revision, groups: catalog.groups, layers, catalog };
}

/** Compare legacy discovery with Catalog without causing a second render path. */
export function shadowDifferences(runtime: CatalogRuntime, legacyKeys: readonly string[]): string[] {
  const catalogKeys = new Set(runtime.layers.map((layer) => layer.key));
  const legacy = new Set(legacyKeys);
  return [
    ...[...catalogKeys].filter((key) => !legacy.has(key)).map((key) => `catalog-only:${key}`),
    ...[...legacy].filter((key) => !catalogKeys.has(key)).map((key) => `legacy-only:${key}`),
  ].sort();
}

export function catalogMode(): CatalogMode {
  const value = import.meta.env.VITE_GIS_CATALOG_MODE ?? 'catalog';
  return value === 'legacy' || value === 'shadow' || value === 'catalog' ? value : 'catalog';
}
