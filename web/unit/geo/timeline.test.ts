import type { GeoLayer, GeoPlacement } from "../../src/map/geo/api";
import { geoModel, stayAt, visibleAt } from "../../src/map/geo/timeline";
import type { MapLink, MapPerson } from "../../src/map/types";
import { done, eq, ok, test } from "../harness";

const person = (id: string, birth: number, death: number, weight = 1): MapPerson => ({
  id, label: id, short: id, birth, death, precision: "year", roles: ["philosopher"], weight,
});
let n = 0;
const row = (entity: string, place: string, role: GeoPlacement["role"], from: number | null = null, to: number | null = null, generated = false): GeoPlacement => ({
  entity, place, role, from, to, status: generated ? "generated" : "verified", generated, statement: `s${String(n++).padStart(3, "0")}`,
});
const place = (id: string, lat: number, lon: number) => ({ id, label: id, lat, lon, status: "verified" as const });
const link = (id: string, subject: string, object: string): MapLink => ({ id, subject, object, type: "influenced_by", status: "verified", generated: false, in_textbook: null });

const descartes = person("descartes", 1596, 1650);
const hume = person("hume", 1711, 1776, 3);
const kant = person("kant", 1724, 1804, 5);
const layer: GeoLayer = {
  places: [place("lahaye", 46.97, 0.7), place("amsterdam", 52.37, 4.9), place("stockholm", 59.33, 18.07), place("edinburgh", 55.95, -3.19), place("konigsberg", 54.71, 20.51)],
  placements: [
    row("descartes", "lahaye", "birth", 1596, 1596),
    row("descartes", "amsterdam", "activity", 1628, 1649),
    row("descartes", "stockholm", "death", 1650, 1650),
    row("hume", "edinburgh", null),
    row("kant", "konigsberg", "birth", 1724, 1724),
    row("kant", "konigsberg", "activity"),
    row("kant", "konigsberg", "death", 1804, 1804),
  ],
  unplaced: [],
  truncated: false,
  limit: 400,
};
const model = geoModel(layer);
const input = { people: [descartes, hume, kant], events: [], links: [link("l1", "kant", "hume")] };

test("Декарт переезжает: место медальона по годам", () => {
  const at = (T: number) => visibleAt(model, input, T).persons.find((p) => p.id === "descartes");
  eq(at(1610)?.place, "lahaye");
  eq(at(1640)?.place, "amsterdam");
  eq([at(1650)?.place, at(1650)?.age], ["stockholm", 0]);
  eq([at(1800)?.place, at(1800)?.age], ["stockholm", 150]);
  eq(at(1801), undefined);
});

test("годы в месте по правилу whereAt", () => {
  const rows = model.byEntity.get("descartes")!;
  const s = (T: number) => {
    const r = stayAt(descartes, rows, T)!;
    return [r.row.place, r.from, r.to, r.after];
  };
  eq(s(1610), ["lahaye", 1596, 1627, false]);
  eq(s(1640), ["amsterdam", 1628, 1649, false]);
  eq(s(1650), ["stockholm", 1650, 1650, false]);
  eq(s(1700), ["stockholm", 1650, 1650, true]);
  eq(stayAt(descartes, rows, 1500), null);
});

test("связь Юм → Кант по годам и по персонам", () => {
  const ln = (T: number) => visibleAt(model, input, T).links.find((l) => l.id === "l1");
  eq(ln(1743), undefined);
  eq([ln(1744)?.from, ln(1744)?.to, ln(1744)?.age], ["hume", "kant", 0]);
  eq(ln(1894)?.age, 150);
  eq(ln(1895), undefined);
});

test("связь без места у конца не считается", () => {
  const lone = person("wolff", 1679, 1754);
  const sc = visibleAt(model, { ...input, people: [...input.people, lone], links: [link("l2", "kant", "wolff")] }, 1760);
  eq(sc.links.length, 0);
  eq(sc.totalLinks, 0);
});

test("порядок персон: ранг в месте, затем порядок мест", () => {
  const ppl = [person("a1", 1700, 1780, 9), person("a2", 1700, 1780, 1), person("b1", 1700, 1780, 2)];
  const L: GeoLayer = { ...layer, placements: [row("a1", "amsterdam", null), row("a2", "amsterdam", null), row("b1", "stockholm", null)] };
  const sc = visibleAt(geoModel(L), { people: ppl, events: [], links: [] }, 1750);
  eq(sc.persons.map((p) => [p.id, p.rank, p.placeIndex]), [["a1", 0, 0], ["b1", 0, 1], ["a2", 1, 0]]);
  ok(sc.places[0].id === "amsterdam", "место с большим числом людей первым");
});

done();
