import { useLayoutEffect, useRef, type RefObject } from "react";
import { useT } from "../../i18n";
import { find } from "../model";
import type { MapData } from "../types";
import type { GeoPlace } from "./api";
import type { Scene, ScenePlace } from "./timeline";

// Панель карты в виде «Глобус» (geo-timeline): текстовая альтернатива глобусу — «Места в
// <год> году», «N без места», пределы; «Выбрано» для отметки места; легенда глобуса. В
// основном бандле, без d3: глобус (ленивый фрагмент) и список живут раздельно. Названия —
// текстовые узлы React, разметка из данных не вставляется.

export type GeoPanel = {
  year: number;
  status: "loading" | "ok" | "error";
  scene: Scene | null;
  unplaced: string[]; // видимые сущности без места
  place: GeoPlace | null; // выбранное место
  noPlace: boolean; // выбранная сущность без места на глобусе
  onPlace: (id: string) => void; // выбор места в списке: выбор и центр вида
};

const label = (data: MapData, id: string) => find(data, id)?.obj.label ?? id;
const MIN_ROWS = 72; // px: меньше — панель складывает разделы (MapPanel, useFit)

// Высота строк мест — остаток панели под ними: панель не прокручивается и не складывает
// «Выбрано» из-за длинного списка; прокручивается сам список.
function useRest(list: RefObject<HTMLUListElement | null>) {
  useLayoutEffect(() => {
    const ul = list.current;
    const panel = ul?.closest<HTMLElement>(".map-panel");
    const body = ul?.closest<HTMLElement>(".map-panel__body");
    if (!ul || !panel || !body) return;
    const style = getComputedStyle(panel);
    const bottom = panel.getBoundingClientRect().top + panel.clientTop + panel.clientHeight - parseFloat(style.paddingBottom);
    const box = ul.getBoundingClientRect();
    const tail = body.getBoundingClientRect().bottom - box.bottom;
    const max = `${Math.max(MIN_ROWS, Math.floor(bottom - box.top - tail - 1))}px`;
    if (ul.style.maxHeight !== max) ul.style.maxHeight = max;
  });
}

export function GeoList({
  data,
  geo,
  sel,
  onSelect,
  onOpenCard,
}: {
  data: MapData;
  geo: GeoPanel;
  sel: string | null;
  onSelect: (id: string) => void;
  onOpenCard: (id: string, title: string) => void;
}) {
  const t = useT();
  const scene = geo.scene;
  const rows = useRef<HTMLUListElement>(null);
  useRest(rows);
  return (
    <section className="map-panel__sec geo-list" data-section="places" aria-label={t.geo.placesIn(geo.year)}>
      <h2 className="map-panel__h">{t.geo.placesIn(geo.year)}</h2>
      {scene && scene.totalPlaces > scene.places.length && (
        <p className="geo-list__limit" data-geo-limit="places">
          {t.geo.placesShown(scene.places.length, scene.totalPlaces)}
        </p>
      )}
      {scene && scene.totalLinks > scene.links.length && (
        <p className="geo-list__limit" data-geo-limit="links">
          {t.geo.linksShown(scene.links.length, scene.totalLinks)}
        </p>
      )}
      {scene && scene.places.length > 0 && (
        <ul className="geo-list__rows" ref={rows}>
          {scene.places.map((p) => (
            <li key={p.id} className="geo-row" data-geo-row={p.id} data-people={p.people.length}>
              <button
                type="button"
                className="geo-row__place"
                aria-pressed={sel === p.id}
                onClick={() => geo.onPlace(p.id)}
              >
                <span className="geo-row__name">{p.label}</span>
                {p.people.length > 0 && <span className="geo-row__count">{t.geo.people(p.people.length)}</span>}
              </button>
              {p.unverified && <span className="geo-row__unverified">{t.geo.unverified}</span>}
              <span className="geo-row__who">
                {[...p.people, ...p.events].map((id) => (
                  <button key={id} type="button" className="map-link-btn" aria-pressed={sel === id} onClick={() => onSelect(id)}>
                    {label(data, id)}
                  </button>
                ))}
              </span>
            </li>
          ))}
        </ul>
      )}
      {geo.unplaced.length > 0 && (
        <details className="geo-list__unplaced">
          <summary data-geo-unplaced={geo.unplaced.length}>{t.geo.unplaced(geo.unplaced.length)}</summary>
          <ul aria-label={t.geo.unplacedList}>
            {geo.unplaced.map((id) => (
              <li key={id}>
                <button type="button" className="map-link-btn" onClick={() => onOpenCard(id, label(data, id))}>
                  {label(data, id)}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

// «Выбрано» для отметки места: «Париж, 1750», люди и события места на год T кнопками.
export function GeoPlaceSelected({
  data,
  place,
  here,
  year,
  onSelect,
}: {
  data: MapData;
  place: GeoPlace;
  here: ScenePlace | null;
  year: number;
  onSelect: (id: string) => void;
}) {
  const t = useT();
  const who = here ? [...here.people, ...here.events] : [];
  return (
    <>
      <h2 className="map-panel__h">
        {t.map.selected} · {t.geo.placeKicker}
      </h2>
      <div className="map-selected__name">{t.geo.placeTitle(place.label, year)}</div>
      {who.length ? (
        <div className="geo-selected__who">
          {who.map((id) => (
            <button key={id} type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => onSelect(id)}>
              {label(data, id)}
            </button>
          ))}
        </div>
      ) : (
        <p className="map-selected__note">{t.geo.nobodyHere}</p>
      )}
    </>
  );
}

// Легенда глобуса: отметка с числом людей, полое кольцо, дуга со стрелкой, пунктир, путь
// выбранного; правило года связи и бледнения; источник береговой линии.
export function GlobeLegend() {
  const t = useT();
  const L = t.geo.legend;
  return (
    <>
      <div className="map-legend geo-legend">
        <span>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <circle className="geo-legend__dot" cx="8" cy="8" r="6" />
          </svg>
          {L.place}
        </span>
        <span>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <circle className="geo-legend__ring" cx="8" cy="8" r="5.5" />
          </svg>
          {L.unverified}
        </span>
        <span>
          <svg viewBox="0 0 34 12" aria-hidden="true">
            <path className="geo-legend__arc" d="M2 10 Q17 0 28 7" />
            <path className="geo-legend__arrow" d="M32 9 L26.5 9.3 L29 4.6 Z" />
          </svg>
          {L.influence}
        </span>
        <span>
          <svg viewBox="0 0 34 12" aria-hidden="true">
            <path className="geo-legend__arc" d="M2 10 Q17 0 32 8" strokeDasharray="4 3" />
          </svg>
          {L.generated}
        </span>
        <span>
          <svg viewBox="0 0 34 12" aria-hidden="true">
            <path className="geo-legend__trail" d="M3 9 L15 4 L31 7" />
          </svg>
          {L.trail}
        </span>
      </div>
      <p className="map-legend__note">{L.rule}</p>
      <p className="map-legend__note">{t.geo.coast}</p>
    </>
  );
}
