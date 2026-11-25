import { useEffect, useRef, useState, type MouseEvent, type RefObject } from "react";
import { navigate } from "../App";
import { openCardInPanel } from "../FullCard";
import { useLang, useT } from "../i18n";
import type { CatalogItem } from "../reference/types";
import { Icon, StatusMark } from "../ui";
import {
  COUNT_GROUP,
  COUNT_KINDS,
  fetchEpochs,
  fetchMembers,
  isAbort,
  spanText,
  wikidataUrl,
  type Epoch,
  type EpochsData,
  type MemberList,
  type UndatedEpoch,
} from "./api";
import { Timeline, TimelinePlaceholder } from "./Timeline";

// Страница эпох (epochs, «Страница эпох»): /epochs и /epochs/<id>. Лента — данные
// GET /v1/epochs; описание выбранной — счётчики из списка, ведущие персоны, труды и события —
// справочником (/v1/catalog?epoch=&type=). Выбор — в адресе: /epochs/<id> (запись истории),
// Esc на ленте — /epochs. Названия и id из адреса выводятся текстом React, без разметки.

type Load = { status: "loading" } | { status: "error" } | { status: "ok"; data: EpochsData };
type Members = Partial<Record<MemberList, CatalogItem[] | "error">>;
const LISTS: MemberList[] = ["people", "works", "events"];

function href(path: string) {
  return (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(path);
  };
}

export function EpochsPage({ epochId }: { epochId: string | null }) {
  const t = useT();
  const lang = useLang();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [retry, setRetry] = useState(0);
  const [members, setMembers] = useState<{ id: string; lists: Members } | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const focusHeading = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoad({ status: "loading" });
    fetchEpochs(controller.signal)
      .then((data) => setLoad({ status: "ok", data }))
      .catch((e) => {
        if (!isAbort(e)) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [retry]);

  const data = load.status === "ok" ? load.data : null;
  const dated = data?.epochs ?? [];
  const undated = data?.undated ?? [];
  const chosen: Epoch | UndatedEpoch | null =
    (epochId && (dated.find((e) => e.id === epochId) ?? undated.find((e) => e.id === epochId))) || null;
  const notFound = data !== null && epochId !== null && chosen === null;

  // Участники выбранной эпохи: три запроса справочника параллельно.
  const chosenId = chosen?.id ?? null;
  useEffect(() => {
    if (!chosenId) return;
    const controller = new AbortController();
    setMembers({ id: chosenId, lists: {} });
    for (const list of LISTS) {
      fetchMembers(chosenId, list, lang, controller.signal)
        .then((items) => setMembers((m) => (m && m.id === chosenId ? { ...m, lists: { ...m.lists, [list]: items } } : m)))
        .catch((e) => {
          if (isAbort(e)) return;
          setMembers((m) => (m && m.id === chosenId ? { ...m, lists: { ...m.lists, [list]: "error" } } : m));
        });
    }
    return () => controller.abort();
  }, [chosenId, lang]);

  // После выбора на ленте фокус — на заголовке описания.
  useEffect(() => {
    if (chosenId && focusHeading.current) {
      focusHeading.current = false;
      heading.current?.focus();
    }
  }, [chosenId]);

  const select = (id: string) => {
    focusHeading.current = true;
    if (id === epochId) heading.current?.focus();
    else navigate(`/epochs/${encodeURIComponent(id)}`);
  };
  const clear = () => {
    if (epochId !== null) navigate("/epochs");
  };

  const empty = data !== null && dated.length === 0 && undated.length === 0;
  return (
    <main className="page epochs">
      <header className="page-header epochs__header">
        <div>
          <h1 className="page-title">{t.epochs.title}</h1>
          <p className="page-lead epochs__lead">{t.epochs.lead}</p>
        </div>
      </header>

      {load.status === "loading" && <TimelinePlaceholder />}
      {load.status === "error" && (
        <div className="pg-notice pg-notice--warning epochs__notice" role="alert">
          <Icon name="info" />
          <div>
            <p>{t.epochs.error}</p>
            <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => setRetry((n) => n + 1)}>
              {t.epochs.retry}
            </button>
          </div>
        </div>
      )}
      {empty && (
        <div className="pg-notice epochs__notice" role="status">
          <Icon name="info" />
          <div>{t.epochs.empty}</div>
        </div>
      )}
      {dated.length > 0 && <Timeline epochs={dated} selected={chosenId} onSelect={select} onClear={clear} />}
      {notFound && (
        <p className="epochs__not-found" role="status">
          {t.epochs.notFound}
        </p>
      )}
      {chosen && (
        <Details
          key={chosen.id}
          epoch={chosen}
          heading={heading}
          lists={members?.id === chosen.id ? members.lists : {}}
        />
      )}
      {undated.length > 0 && (
        <section className="epochs__undated" aria-labelledby="epochs-undated">
          <h2 id="epochs-undated" className="epochs__undated-title">
            {t.epochs.undated}
          </h2>
          <ul className="epochs__undated-list">
            {undated.map((e) => (
              <li key={e.id}>
                <a className="epochs__undated-link" href={`/epochs/${encodeURIComponent(e.id)}`} onClick={href(`/epochs/${encodeURIComponent(e.id)}`)}>
                  {e.label}
                </a>
                <span className="epochs__undated-count"> {t.epochs.members(total(e.counts))}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

const total = (c: Epoch["counts"]) => COUNT_KINDS.reduce((n, k) => n + c[k], 0);
const isDated = (e: Epoch | UndatedEpoch): e is Epoch => "from" in e;

function itemDates(item: CatalogItem): string | null {
  return item.dates ? item.dates.original || `${item.dates.from}–${item.dates.to}` : null;
}

function Details({
  epoch,
  heading,
  lists,
}: {
  epoch: Epoch | UndatedEpoch;
  heading: RefObject<HTMLHeadingElement>;
  lists: Members;
}) {
  const t = useT();
  const id = encodeURIComponent(epoch.id);
  const dated = isDated(epoch) ? epoch : null;
  const range = dated ? spanText(dated.from, dated.to, t.epochs.bce) : null;
  const wikidata = dated ? wikidataUrl(dated.dating.wikidata) : null;
  const shown = COUNT_KINDS.filter((k) => epoch.counts[k] > 0);
  return (
    <section className="epochs-details" aria-labelledby="epochs-details-title">
      <h2 id="epochs-details-title" className="epochs-details__title" tabIndex={-1} ref={heading}>
        {epoch.label}
      </h2>
      <p className="epochs-details__dating">
        {dated ? (
          <>
            <span className="epochs-details__range">{range}</span>
            {dated.original && dated.original !== range && <span className="epochs-details__original"> ({dated.original})</span>}
            <span className="epochs-details__source">
              {" · "}
              {t.epochs.source[dated.dating.source]}
            </span>
            {wikidata && (
              <>
                {" · "}
                <a className="epochs-details__wikidata" href={wikidata} target="_blank" rel="noopener noreferrer">
                  {t.epochs.wikidata}
                </a>
              </>
            )}
          </>
        ) : (
          t.epochs.undated
        )}
      </p>
      <div className="epochs-details__actions">
        {dated && (
          <a className="pg-btn pg-btn--secondary pg-btn--sm" href={`/graph?epochs=${id}`} onClick={href(`/graph?epochs=${id}`)}>
            {t.epochs.onMap}
          </a>
        )}
        <a className="pg-btn pg-btn--secondary pg-btn--sm" href={`/reference?epoch=${id}`} onClick={href(`/reference?epoch=${id}`)}>
          {t.epochs.inReference}
        </a>
        <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm" onClick={() => openCardInPanel(epoch.id, epoch.label)}>
          {t.epochs.card}
        </button>
      </div>
      {dated?.summary && (
        <p className="epochs-details__summary">
          <span>{dated.summary.text}</span>
          {dated.summary.generated && (
            <span className="epochs-details__generated" data-generated="true">
              {" "}
              <StatusMark status="generated" />
            </span>
          )}
        </p>
      )}
      <p className="epochs-details__counts">
        {shown.length
          ? shown.map((k, i) => (
              <span key={k}>
                {i > 0 && " · "}
                <a
                  className="epochs-details__count"
                  data-count={k}
                  href={`/reference?epoch=${id}&group=${COUNT_GROUP[k]}`}
                  onClick={href(`/reference?epoch=${id}&group=${COUNT_GROUP[k]}`)}
                >
                  {t.epochs.counts[k]} {epoch.counts[k]}
                </a>
              </span>
            ))
          : t.epochs.nothing}
      </p>
      <div className="epochs-details__lists">
        {LISTS.map((list) => (
          <MemberColumn key={list} list={list} items={lists[list]} />
        ))}
      </div>
    </section>
  );
}

function MemberColumn({ list, items }: { list: MemberList; items: CatalogItem[] | "error" | undefined }) {
  const t = useT();
  if (Array.isArray(items) && items.length === 0) return null;
  return (
    <section className="epochs-members" data-list={list} aria-label={t.epochs.lists[list]} aria-busy={items === undefined}>
      <h3 className="epochs-members__title">{t.epochs.lists[list]}</h3>
      {items === undefined && <span className="epochs-members__placeholder" aria-hidden="true" />}
      {items === "error" && <p className="epochs-members__error">{t.epochs.listFailed}</p>}
      {Array.isArray(items) && (
        <ul className="epochs-members__list">
          {items.map((item) => {
            const dates = itemDates(item);
            return (
              <li key={item.id}>
                <button type="button" className="epochs-members__item" onClick={() => openCardInPanel(item.id, item.label)}>
                  {list === "events" && dates && <span className="epochs-members__year">{dates}</span>}
                  <span className="epochs-members__name">{item.label}</span>
                  {list !== "events" && dates && <span className="epochs-members__year">{dates}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
