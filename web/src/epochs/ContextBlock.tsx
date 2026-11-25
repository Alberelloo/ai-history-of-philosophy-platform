import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { navigate } from "../App";
import { openCardInPanel } from "../FullCard";
import { pick, useLang, useT } from "../i18n";
import { KNOWLEDGE_API, ndjson } from "../map/stream";
import { useScope } from "../scope";
import { storage } from "../storage";
import { Icon, StatusMark } from "../ui";
import {
  CONTEXT_KINDS,
  fetchContext,
  isAbort,
  wikidataUrl,
  yearText,
  type ContextData,
  type ContextEvent,
  type ContextKind,
  type ContextLink,
} from "./api";

// Блок «Контекст эпохи» (epoch-context, «Контекст на странице эпохи»): события эпохи по
// группам вида и что они стимулировали — данные GET /v1/context (правила на сервере: порядок,
// пределы, закрытые источники). Фильтр групп и «только проверенные» — в адресе страницы
// (kinds, verified=1; замена адреса без новой записи истории). «Достроить контекст» — общий
// поток графа (/graph/build, рецепт context): новые связи — с пометкой «не проверено»,
// после done блок перезапрашивает контекст. Названия выводятся текстом React, без разметки.

type Load = { status: "loading" } | { status: "error" } | { status: "ok"; data: ContextData };
type Build = { running: boolean; message: string | null; added: ContextLink[] };
const STIMULATED = "stimulated";

function readAddress(): { kinds: ContextKind[]; verified: boolean } {
  const p = new URLSearchParams(window.location.search);
  const raw = (p.get("kinds") ?? "").split(",");
  const kinds = CONTEXT_KINDS.filter((k) => raw.includes(k));
  return { kinds, verified: p.get("verified") === "1" };
}

function writeAddress(kinds: ContextKind[], verified: boolean): void {
  const p = new URLSearchParams(window.location.search);
  if (kinds.length) p.set("kinds", kinds.join(","));
  else p.delete("kinds");
  if (verified) p.set("verified", "1");
  else p.delete("verified");
  const search = p.toString();
  const url = window.location.pathname + (search ? `?${search}` : "") + window.location.hash;
  window.history.replaceState(window.history.state, "", url);
}

function follow(path: string) {
  return (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(path);
  };
}

const kindOf = (e: ContextEvent): ContextKind =>
  (CONTEXT_KINDS as readonly string[]).includes(e.kind ?? "") ? (e.kind as ContextKind) : "none";

export function ContextBlock({ epochId }: { epochId: string }) {
  const t = useT();
  const c = t.epochs.context;
  const lang = useLang();
  const scope = useScope();
  const textbook = storage.currentSource() ?? null;
  const onlyTextbook = scope.onlyTextbook && Boolean(textbook);
  const [filter, setFilter] = useState(readAddress);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [reload, setReload] = useState(0);
  const [builds, setBuilds] = useState<Record<string, Build>>({});
  const [announce, setAnnounce] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLoad((l) => (l.status === "ok" ? l : { status: "loading" }));
    fetchContext(epochId, { kinds: filter.kinds, verified: filter.verified, textbook, lang }, controller.signal)
      .then((data) => setLoad({ status: "ok", data }))
      .catch((e) => {
        if (!isAbort(e)) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [epochId, filter, textbook, lang, reload]);

  const change = (next: { kinds: ContextKind[]; verified: boolean }) => {
    writeAddress(next.kinds, next.verified);
    setFilter(next);
  };
  const toggleKind = (k: ContextKind) => {
    const kinds = filter.kinds.includes(k) ? filter.kinds.filter((x) => x !== k) : [...filter.kinds, k];
    change({ ...filter, kinds: CONTEXT_KINDS.filter((x) => kinds.includes(x)) });
  };

  const extensionText = (code: string | null | undefined): string | null => {
    if (!code || code === "pending") return null;
    if (code === "not_needed") return c.notNeeded;
    if (code === "done_before") return c.doneBefore;
    if (code === "scope") return c.scope;
    return pick(t.graph.notices, code) ?? c.failed;
  };

  async function extend(event: ContextEvent) {
    const set = (patch: Partial<Build>) =>
      setBuilds((b) => ({ ...b, [event.id]: { ...{ running: false, message: null, added: [] }, ...b[event.id], ...patch } }));
    set({ running: true, message: null });
    const names = new Map<string, { label: string; type: string }>();
    const remember = (nodes: unknown) => {
      for (const n of (nodes as { id: string; label: string; type: string }[] | undefined) ?? []) names.set(n.id, n);
    };
    const added: ContextLink[] = [];
    try {
      const response = await fetch(`${KNOWLEDGE_API}/graph/build`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entity_id: event.id,
          recipe: "context",
          depth: null,
          textbook,
          only_textbook: onlyTextbook,
          generation: scope.generation,
        }),
      });
      if (!response.ok) {
        set({ running: false, message: c.failed });
        return;
      }
      for await (const item of ndjson(response)) {
        if (item.type === "graph") {
          remember(item.nodes);
          set({ message: extensionText(item.extension as string | null) });
        } else if (item.type === "edge") {
          remember(item.nodes);
          const edge = item.edge as { id: string; subject: string; object: string; type: string };
          if (edge.type !== STIMULATED || edge.subject !== event.id) continue;
          const target = names.get(edge.object);
          added.push({
            statement_id: edge.id,
            target: { id: edge.object, label: target?.label ?? edge.object, type: target?.type ?? "" },
            mechanism: null, // механизм от модели не принимается (сервер его не сохраняет)
            status: "generated",
            generated: true,
            in_textbook: null,
            attributed_to: [],
            evidence: [],
            pending: true,
          });
          set({ added: [...added] });
        } else if (item.type === "notice") {
          set({ message: extensionText(item.extension as string) });
        }
      }
      set({ running: false });
      if (added.length) setAnnounce(c.added(added.length));
      setReload((n) => n + 1); // сохранение — через очередь: перезапрос показывает сохранённое
    } catch {
      set({ running: false, message: c.failed });
    }
  }

  const data = load.status === "ok" ? load.data : null;
  const counts = data?.counts ?? {};
  const totalAll = CONTEXT_KINDS.reduce((n, k) => n + (counts[k] ?? 0), 0);
  const totalShown = filter.kinds.length ? filter.kinds.reduce((n, k) => n + (counts[k] ?? 0), 0) : totalAll;
  const groups = useMemo(() => {
    const by = new Map<ContextKind, ContextEvent[]>();
    for (const e of data?.events ?? []) {
      const k = kindOf(e);
      by.set(k, [...(by.get(k) ?? []), e]);
    }
    return CONTEXT_KINDS.filter((k) => by.has(k)).map((k) => ({ kind: k, events: by.get(k)! }));
  }, [data]);
  const kindsWithEvents = CONTEXT_KINDS.filter((k) => (counts[k] ?? 0) > 0);

  return (
    <section className="epochs-context" aria-labelledby="epochs-context-title" aria-busy={load.status === "loading"}>
      <div className="epochs-context__head">
        <h3 id="epochs-context-title" className="epochs-context__title">
          {c.title}
        </h3>
        <label className="epochs-context__verified">
          <input
            type="checkbox"
            checked={filter.verified}
            onChange={(e) => change({ ...filter, verified: e.target.checked })}
          />{" "}
          {c.verifiedOnly}
        </label>
      </div>
      {data && totalAll > 0 && (
        <div className="epochs-context__kinds" role="group" aria-label={c.kindsLabel}>
          <button
            type="button"
            className="pg-btn pg-btn--ghost pg-btn--sm epochs-context__kind"
            aria-pressed={filter.kinds.length === 0}
            onClick={() => change({ ...filter, kinds: [] })}
          >
            {c.all} {totalAll}
          </button>
          {kindsWithEvents.map((k) => (
            <button
              key={k}
              type="button"
              className="pg-btn pg-btn--ghost pg-btn--sm epochs-context__kind"
              data-kind={k}
              aria-pressed={filter.kinds.includes(k)}
              onClick={() => toggleKind(k)}
            >
              {c.kinds[k]} {counts[k]}
            </button>
          ))}
        </div>
      )}
      {load.status === "loading" && (
        <p className="epochs-context__state" role="status">
          {c.loading}
        </p>
      )}
      {load.status === "error" && (
        <div className="pg-notice pg-notice--warning epochs-context__state" role="alert">
          <Icon name="info" />
          <div>
            <p>{c.error}</p>
            <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => setReload((n) => n + 1)}>
              {c.retry}
            </button>
          </div>
        </div>
      )}
      {data && totalAll === 0 && (
        <p className="epochs-context__state epochs-context__empty" role="status">
          {c.empty}
        </p>
      )}
      {data?.truncated && (
        <p className="epochs-context__state epochs-context__partial" role="status">
          {c.partial(data.events.length, totalShown)}
        </p>
      )}
      {groups.map((g) => (
        <section key={g.kind} className="epochs-context__group" data-group={g.kind} aria-label={c.kinds[g.kind]}>
          <h4 className="epochs-context__group-title">{c.kinds[g.kind]}</h4>
          {g.events.map((e) => (
            <ContextEventItem
              key={e.id}
              event={e}
              build={builds[e.id]}
              canExtend={scope.generation}
              onExtend={() => extend(e)}
            />
          ))}
        </section>
      ))}
      <p className="epochs-context__live" aria-live="polite">
        {announce}
      </p>
    </section>
  );
}

function ContextEventItem({
  event,
  build,
  canExtend,
  onExtend,
}: {
  event: ContextEvent;
  build: Build | undefined;
  canExtend: boolean;
  onExtend: () => void;
}) {
  const t = useT();
  const c = t.epochs.context;
  const year = event.dates ? yearText(event.dates.from, t.epochs.bce) : null;
  const wikidata = wikidataUrl(event.wikidata);
  const saved = new Set(event.stimulated.map((l) => l.target.id));
  const links = [...event.stimulated, ...(build?.added ?? []).filter((l) => !saved.has(l.target.id))];
  return (
    <article className="epochs-context__event" data-event={event.id}>
      <div className="epochs-context__event-head">
        <h5 className="epochs-context__event-title">
          {year && <span className="epochs-context__year">{year} </span>}
          <button type="button" className="epochs-context__name" onClick={() => openCardInPanel(event.id, event.label)}>
            {event.label}
          </button>
          {event.places.length > 0 && (
            <span className="epochs-context__place"> · {event.places.map((p) => p.label).join(", ")}</span>
          )}
          {wikidata && (
            <>
              {" · "}
              <a className="epochs-context__wikidata" href={wikidata} target="_blank" rel="noopener noreferrer">
                {t.epochs.wikidata}
              </a>
            </>
          )}
        </h5>
        {canExtend && (
          <button
            type="button"
            className="pg-btn pg-btn--ghost pg-btn--sm epochs-context__extend"
            onClick={onExtend}
            disabled={build?.running}
          >
            {build?.running ? c.extending : c.extend}
          </button>
        )}
      </div>
      {build?.message && (
        <p className="epochs-context__notice" role="status">
          {build.message}
        </p>
      )}
      {links.length === 0 ? (
        <p className="epochs-context__no-links">{c.noLinks}</p>
      ) : (
        <ul className="epochs-context__links" aria-label={c.stimulated}>
          {links.map((l) => (
            <ContextLinkRow key={l.statement_id} link={l} />
          ))}
        </ul>
      )}
    </article>
  );
}

function ContextLinkRow({ link }: { link: ContextLink }) {
  const t = useT();
  const c = t.epochs.context;
  const unverified = link.generated || link.pending === true;
  const mechanism = link.mechanism ? (pick(t.onto.qualifiers.mechanism, link.mechanism) ?? link.mechanism) : null;
  return (
    <li
      className={unverified ? "epochs-context__link is-unverified" : "epochs-context__link"}
      data-statement={link.statement_id}
      data-status={link.status}
      data-unverified={unverified ? "true" : "false"}
    >
      <span className="epochs-context__arrow" aria-hidden="true">
        →{" "}
      </span>
      <button type="button" className="epochs-context__target" onClick={() => openCardInPanel(link.target.id, link.target.label)}>
        {link.target.label}
      </button>
      <span className="epochs-context__sep"> · </span>
      <span className={mechanism ? "epochs-context__mechanism" : "epochs-context__mechanism is-missing"}>
        {mechanism ?? c.noMechanism}
      </span>
      <span className="epochs-context__sep"> · </span>
      {unverified ? (
        <StatusMark status="generated">{c.unverified}</StatusMark>
      ) : (
        <StatusMark status={link.status === "verified" ? "verified" : "sourced"}>{c.status[link.status === "verified" ? "verified" : "sourced"]}</StatusMark>
      )}
      {link.pending && <span className="epochs-context__pending"> ({c.pending})</span>}
      {link.evidence.map((e, i) => (
        <span key={e.paragraph_id}>
          <span className="epochs-context__sep"> · </span>
          <a className="epochs-context__evidence pg-cite" href={e.link} aria-label={c.evidence(i + 1)} onClick={follow(e.link)}>
            ¶
          </a>
        </span>
      ))}
      {link.attributed_to.length > 0 && <span className="epochs-context__who"> {link.attributed_to.join(", ")}</span>}
    </li>
  );
}
