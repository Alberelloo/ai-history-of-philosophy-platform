import { navigate } from "../App";
import { pick, relationTitle, useT, whoLabel } from "../i18n";
import { Generated, Icon, StatusMark } from "../ui";

// Подробности связи — прежняя разметка graph-details из GraphPage: тип, уточнители,
// атрибуции с позициями, подтверждения с цитатами и ссылками на абзацы, статус и согласие.

export type GEdge = {
  id: string;
  subject: string;
  object: string;
  type: string;
  title: string;
  status: string;
  generated: boolean;
  consensus: string;
  qualifiers: Record<string, unknown>;
  attributions: { who: string; kind?: string; stance: string; place: string | null }[];
  evidence: { paragraph_id: string; quote: string; link: string }[];
  in_textbook: boolean | null;
};

export function LinkDetails({
  edge,
  label,
  onClose,
}: {
  edge: GEdge;
  label: (id: string) => string;
  onClose: () => void;
}) {
  const t = useT();
  return (
    <div className="graph-details map-link" role="region" aria-label={t.graph.edge}>
      <div className="map-link__head">
        <h2 className="section-title">
          {label(edge.subject)} — {relationTitle(t, edge.type, false, edge.title)} — {label(edge.object)}
        </h2>
        <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm" onClick={onClose} aria-label={t.map.closeLink}>
          <Icon name="close" small />
        </button>
      </div>
      <p className="graph-details__status">
        <span className="muted">{t.graph.statusLabel}:</span>{" "}
        {edge.status === "verified" || edge.status === "sourced" || edge.status === "generated" ? (
          <StatusMark status={edge.status} />
        ) : (
          (pick(t.status, edge.status) ?? edge.status)
        )}
        {edge.consensus === "disputed" && <StatusMark status="disputed" />}
        {edge.in_textbook === true && <span className="badge">{t.scope.inTextbook}</span>}
        {edge.in_textbook === false && <span className="badge">{t.scope.notInTextbookMark}</span>}
      </p>
      {edge.generated && (
        <p className="pg-desc">
          <Generated className="card-description ungrounded">{t.graph.generatedNote}</Generated>
        </p>
      )}
      {Object.keys(edge.qualifiers).length > 0 && (
        <p className="muted">
          {Object.entries(edge.qualifiers)
            .map(([k, v]) => `${k}: ${String(v)}`)
            .join("; ")}
        </p>
      )}
      {edge.attributions.length > 0 && (
        <ul className="graph-who">
          {edge.attributions.map((a, i) => (
            <li key={i}>
              {t.card.believes(whoLabel(t, a))} ({pick(t.graph.stance, a.stance) ?? a.stance}
              {a.place ? `, ${a.place}` : ""})
            </li>
          ))}
        </ul>
      )}
      {edge.evidence.map((ev, i) => (
        <blockquote key={ev.paragraph_id} className="selection-context">
          «{ev.quote}»
          <a
            className="citation pg-cite"
            href={ev.link}
            title={t.card.evidence(i + 1)}
            onClick={(x) => {
              x.preventDefault();
              navigate(ev.link);
            }}
          >
            {i + 1}
          </a>
        </blockquote>
      ))}
    </div>
  );
}
