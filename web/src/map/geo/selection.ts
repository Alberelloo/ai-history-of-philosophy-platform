// Выбор на глобусе (geo-timeline, rework-globe-political-map): какие медальоны, значки
// событий и дуги выделены и каким цветом. Цвета — роли выбора карты (model.ts, related):
// self, teacher, student, c1…c6, other; остальное при любом выборе приглушено (data-dim).
// Без DOM и без d3.

import type { ColorRole, Related } from "../model";
import type { GeoPlace } from "./api";
import { startOf, type GeoModel, type Scene } from "./timeline";

export type GlobeRoles = {
  active: boolean; // есть выбор: невыделенное приглушается
  persons: Map<string, ColorRole>;
  events: Map<string, ColorRole>;
  links: Map<string, ColorRole>;
  trail: GeoPlace[]; // места выбранной персоны по порядку лет (линия «путь жизни»)
};

const NONE: GlobeRoles = { active: false, persons: new Map(), events: new Map(), links: new Map(), trail: [] };

export function globeRoles(model: GeoModel | null, scene: Scene | null, rel: Related | null, place: string | null): GlobeRoles {
  if (!model || !scene) return NONE;
  if (place && model.places.has(place)) {
    // Место (строка списка или значок «+N»): его люди и события на год T.
    const persons = new Map<string, ColorRole>(scene.persons.filter((p) => p.place === place).map((p) => [p.id, "self"]));
    const events = new Map<string, ColorRole>(scene.events.filter((e) => e.place === place).map((e) => [e.id, "self"]));
    return { active: true, persons, events, links: new Map(), trail: [] };
  }
  if (!rel) return NONE;
  const persons = new Map<string, ColorRole>();
  const events = new Map<string, ColorRole>();
  const links = new Map<string, ColorRole>(rel.links.map((x) => [x.link.id, x.role]));
  for (const p of scene.persons) {
    const role = rel.people.get(p.id);
    if (role) persons.set(p.id, role);
  }
  let trail: GeoPlace[] = [];
  if (rel.type === "person") {
    const p = rel.obj;
    persons.set(p.id, "self");
    const rows = [...(model.byEntity.get(p.id) ?? [])].sort((a, b) => startOf(p, a) - startOf(p, b) || (a.statement < b.statement ? -1 : 1));
    const seen = new Set<string>();
    for (const r of rows) {
      const g = model.places.get(r.place);
      if (g && !seen.has(g.id)) {
        seen.add(g.id);
        trail.push(g);
      }
    }
    if (trail.length < 2) trail = [];
  } else if (rel.type === "event") {
    events.set(rel.obj.id, "self");
  }
  return { active: true, persons, events, links, trail };
}
