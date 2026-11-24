/** Presentation-only role areas for the Tribe map. */
const AREAS: Record<string, { x: number; y: number }> = {
  "ember-guard": { x: 50, y: 23 }, "river-scouts": { x: 24, y: 34 },
  "stone-builders": { x: 43, y: 65 }, "dawn-hunters": { x: 20, y: 61 },
  "elder-council": { x: 39, y: 43 }, "ash-shamans": { x: 63, y: 40 },
  "granary-keepers": { x: 55, y: 76 }, "fire-diplomats": { x: 73, y: 59 },
  "black-hill-tribe": { x: 80, y: 23 }, "wolf-tooth-raiders": { x: 82, y: 76 },
  "salt-road-caravan": { x: 15, y: 78 },
};

export function tribeActivityCenter(id: string, fallbackX: number, fallbackY: number) {
  return AREAS[id] || { x: fallbackX, y: fallbackY };
}
