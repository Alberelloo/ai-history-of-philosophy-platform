// Выбор на глобусе (geo-timeline): какие отметки и дуги выделены и каким цветом. Цвета —
// роли выбора карты (model.ts, related): self, teacher, student, c1…c6, other; остальное
// при любом выборе приглушено (data-dim). Без DOM и без d3.

import type { ColorRole, Related } from "../model";
import type { GeoPlace } from "./api";
import { startOf, type GeoModel, type Scene } from "./timeline";

export type GlobeRoles = {
  active: boolean; // есть выбор: невыделенное приглушается
  places: Map<string, ColorRole>;
  links: Map<string, ColorRole>;
  trail: GeoPlace[]; // места выбранной персоны по порядку лет (линия «путь жизни»)
};

const NONE: GlobeRoles = { active: false, places: new Map(), links: new Map(), trail: [] };
// Порядок, в котором роль людей отметки становится ролью отметки.
const ORDER: ColorRole[] = ["self", "teacher", "student", "c1", "c2", "c3", "c4", "c5", "c6", "other"];

export function globeRoles(model: GeoModel | null, scene: Scene | null, rel: Related | null, place: string | null): GlobeRoles {
  if (!model || !scene) return NONE;
  if (place && model.places.has(place)) {
    return { active: true, places: new Map([[place, "self"]]), links: new Map(), trail: [] };
  }
  if (!rel) return NONE;
  const places = new Map<string, ColorRole>();
  const links = new Map<string, ColorRole>(rel.links.map((x) => [x.link.id, x.role]));
  let trail: GeoPlace[] = [];
  const own = (id: string) => (model.byEntity.get(id) ?? []).map((r) => r.place);
  if (rel.type === "person") {
    const p = rel.obj;
    const rows = [...(model.byEntity.get(p.id) ?? [])].sort((a, b) => startOf(p, a) - startOf(p, b) || (a.statement < b.statement ? -1 : 1));
    const seen = new Set<string>();
    for (const r of rows) {
      const g = model.places.get(r.place);
      if (g && !seen.has(g.id)) {
        seen.add(g.id);
        trail.push(g);
      }
      places.set(r.place, "self");
    }
    if (trail.length < 2) trail = [];
  } else if (rel.type === "event") {
    own(rel.obj.id).forEach((id) => places.set(id, "self"));
  }
  // Отметки на год T: роль — у кого из её людей она «старше» по ORDER.
  for (const sp of scene.places) {
    if (places.has(sp.id)) continue;
    let best: ColorRole | null = null;
    for (const id of sp.people) {
      const role = rel.people.get(id);
      if (role && (best == null || ORDER.indexOf(role) < ORDER.indexOf(best))) best = role;
    }
    if (best) places.set(sp.id, best);
  }
  return { active: true, places, links, trail };
}
