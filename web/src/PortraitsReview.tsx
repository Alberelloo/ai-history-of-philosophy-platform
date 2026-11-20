import { useCallback, useEffect, useState } from "react";
import { ApiError, knowledgeApi } from "./api";
import { errorText, pick, useT } from "./i18n";
import { Icon, Portrait } from "./ui";

// Секция проверки портретов внутри страницы проверки оператора: очередь черновиков,
// списки подтверждённых и скрытых, действия «Подтвердить», «Скрыть», «Вернуть»,
// «Сделать главным». Превью черновика сервер не отдаёт (адрес отвечает 404 до
// подтверждения), поэтому вместо битой картинки показываем монограмму с подписью.

type PortraitRow = {
  id: number;
  entity_id: string;
  label: string;
  file_id: string;
  width: number;
  height: number;
  author: string | null;
  year: string | null;
  license: string;
  license_url: string | null;
  source_url: string;
  position: number;
  status: "draft" | "approved";
  hidden: boolean;
  created_at: string;
};

// Ошибка — код и текст сервиса; переводится при показе.
type Problem = { kind?: string; text?: string };
const readError = (e: unknown): Problem =>
  e instanceof ApiError ? { kind: e.details.kind as string | undefined, text: e.details.error as string | undefined } : {};
type Status = "draft" | "approved" | "hidden";
const STATUSES: Status[] = ["draft", "approved", "hidden"];

export function PortraitsReview() {
  const t = useT();
  const [status, setStatus] = useState<Status>("draft");
  const [items, setItems] = useState<PortraitRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<Problem | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setLoaded(false);
    try {
      setItems(await knowledgeApi.portraits<PortraitRow[]>(status));
    } catch (e) {
      setError(readError(e));
      setItems([]);
    }
    setLoaded(true);
  }, [status]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (id: number, action: string) => {
    setError(null);
    try {
      await knowledgeApi.portraitAction(id, action);
    } catch (e) {
      setError(readError(e));
      return;
    }
    await load();
  };

  const empty = status === "hidden" ? t.review.hiddenEmpty : t.review.portraitsEmpty;

  return (
    <section className="review-portraits" aria-label={t.review.portraits}>
      <div className="pg-field review-kind">
        <label className="pg-field__label" htmlFor="portrait-status">
          {t.review.portraitKind}
        </label>
        <div className="pg-field__control select">
          <select
            id="portrait-status"
            className="pg-input"
            value={status}
            onChange={(e) => setStatus(e.target.value as Status)}
          >
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {pick(t.review.portraitKinds, value) ?? value}
              </option>
            ))}
          </select>
          <Icon name="chevronDown" small className="select__chevron" />
        </div>
      </div>

      {error && (
        <div className="pg-notice pg-notice--danger" role="alert">
          <Icon name="warning" />
          <div>{errorText(t, error.kind, error.text)}</div>
        </div>
      )}

      {loaded && items.length === 0 && <p className="muted">{empty}</p>}

      <ol className="review-queue">
        {items.map((item) => (
          <PortraitRowView key={item.id} item={item} onAction={act} />
        ))}
      </ol>
    </section>
  );
}

function PortraitRowView({
  item,
  onAction,
}: {
  item: PortraitRow;
  onAction: (id: number, action: string) => void;
}) {
  const t = useT();
  const showImage = item.status === "approved" && !item.hidden;
  const authorYear = [item.author, item.year].filter(Boolean).join(", ");
  const preview = showImage
    ? { url: knowledgeApi.portraitUrl(item.id), width: item.width, height: item.height }
    : null;

  return (
    <li className="review-item" data-id={item.id} data-status={item.status}>
      <span className="review-portrait__preview" style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <Portrait name={item.label} size={64} portrait={preview} />
        {!item.hidden && item.status === "draft" && (
          <span className="muted">{t.review.previewPending}</span>
        )}
      </span>
      <span
        className="review-portrait__info"
        style={{ display: "grid", gap: "0.25rem", flex: "1 1 16rem", minWidth: "16rem" }}
      >
        <b>{item.label}</b>
        {authorYear && <span className="muted">{authorYear}</span>}
        <span>
          {item.license_url ? (
            <a href={item.license_url} target="_blank" rel="noreferrer">
              {t.review.portraitLicense}: {item.license}
            </a>
          ) : (
            `${t.review.portraitLicense}: ${item.license}`
          )}
        </span>
        <a href={item.source_url} target="_blank" rel="noreferrer">
          {t.review.portraitSource}
        </a>
        <span className="muted">{t.review.portraitSize(item.width, item.height)}</span>
      </span>
      <span className="actions">
        {item.status === "draft" && (
          <button className="pg-btn pg-btn--primary pg-btn--sm" onClick={() => onAction(item.id, "approve")}>
            {t.review.approve}
          </button>
        )}
        {item.status === "approved" && !item.hidden && (
          <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => onAction(item.id, "main")}>
            {t.review.makeMain}
          </button>
        )}
        {!item.hidden && (
          <button className="pg-btn pg-btn--ghost pg-btn--sm" onClick={() => onAction(item.id, "hide")}>
            {t.review.hide}
          </button>
        )}
        {item.hidden && (
          <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => onAction(item.id, "show")}>
            {t.review.show}
          </button>
        )}
      </span>
    </li>
  );
}
