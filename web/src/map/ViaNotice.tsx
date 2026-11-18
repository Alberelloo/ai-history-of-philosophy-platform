// Пометка «Вид подобран ассистентом» в панели карты (assistant-map-view): перечень применённого строится только
// из состояния карты и её данных — выбор, группы и коды, которых на карте нет, не называются.
// Текст из адреса и текст модели сюда не попадают.
import { pick, useT, type Catalog } from "../i18n";
import { Icon } from "../ui";
import { find } from "./model";
import { STRATA, type MapData, type MapState } from "./types";

export function viewSummary(t: Catalog, data: MapData, state: MapState): string[] {
  const f = state.filter;
  const parts: string[] = [];
  const found = state.sel ? find(data, state.sel) : null;
  if (found) parts.push(`${t.map.via.selected}: ${found.obj.label}`);
  const groups = data.groups.filter((g) => f.groups.includes(g.id)).map((g) => g.label);
  if (groups.length) parts.push(`${t.map.via.groups}: ${groups.join(", ")}`);
  if (f.from != null || f.to != null) {
    const [lo, hi] = data.range ?? [f.from ?? 0, f.to ?? 0];
    parts.push(`${t.map.via.years}: ${f.from ?? lo}–${f.to ?? hi}`);
  }
  const named = (codes: string[], names: object, present: Set<string>) =>
    codes.filter((c) => present.has(c)).map((c) => pick(names, c) ?? c);
  const roles = named(f.roles, t.onto.values.person_role, new Set(data.people.flatMap((p) => p.roles)));
  if (roles.length) parts.push(`${t.map.via.roles}: ${roles.join(", ")}`);
  const kinds = named(f.kinds, t.map.kinds, new Set(data.works.map((w) => w.kind)));
  if (kinds.length) parts.push(`${t.map.via.kinds}: ${kinds.join(", ")}`);
  const ekinds = named(f.ekinds, t.onto.values.event_kind, new Set(data.events.map((e) => e.kind ?? "")));
  if (ekinds.length) parts.push(`${t.map.via.ekinds}: ${ekinds.join(", ")}`);
  if (f.verified) parts.push(t.map.via.verified);
  const lens = STRATA.filter((k) => state.collapsed.includes(k)).map((k) => t.map.strata[k].toLocaleLowerCase());
  if (lens.length) parts.push(`${t.map.via.lens}: ${lens.join(", ")}`);
  return parts;
}

export function ViaNotice({ data, state, onReset }: { data: MapData; state: MapState; onReset: () => void }) {
  const t = useT();
  const parts = viewSummary(t, data, state);
  return (
    <section className="map-panel__sec map-via" data-section="via" role="status" aria-label={t.map.via.title}>
      <p className="map-via__title">
        <Icon name="info" small />
        {t.map.via.title}
      </p>
      <p className="map-via__parts">{parts.length ? parts.join("; ") : t.map.via.none}</p>
      <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm map-via__reset" onClick={onReset}>
        {t.map.via.reset}
      </button>
    </section>
  );
}
