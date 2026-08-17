/** UI-only accents; authoritative cartography remains in GeoServer styles. */
const ACCENTS: Record<string, string> = {
  river: '#2fe6d6',
  cross_section: '#f4c95d',
  gate: '#ff8a65',
  pump: '#b58cff',
  administrative_area: '#7898aa',
};

/** Return a stable accent without creating a second browser renderer. */
export function layerAccent(layerKey: string): string {
  return ACCENTS[layerKey] ?? '#38a8ff';
}
