import { navigate } from "./App";
import { useT } from "./i18n";
import { Icon, type IconName } from "./ui";

// Разделы продукта, которые видны в боковой панели сразу, но ещё не работают
// (docs/product/vision.md, «Сценарии» и «Объём»). Страница говорит, что раздел будет делать,
// для какого сценария и в каком он состоянии. Выдуманных данных нет.

export type SoonCode =
  | "assistant"
  | "graph"
  | "reference"
  | "epochs"
  | "compare"
  | "route"
  | "materials"
  | "collections";

export const SOON: { code: SoonCode; icon: IconName; group: "explore" | "mine"; status: "progress" | "later" }[] = [
  { code: "assistant", icon: "chat", group: "explore", status: "progress" },
  { code: "graph", icon: "graph", group: "explore", status: "progress" },
  { code: "reference", icon: "index", group: "explore", status: "progress" },
  { code: "epochs", icon: "timeline", group: "explore", status: "progress" },
  { code: "compare", icon: "scales", group: "explore", status: "later" },
  { code: "route", icon: "route", group: "explore", status: "later" },
  { code: "materials", icon: "upload", group: "mine", status: "later" },
  { code: "collections", icon: "share", group: "mine", status: "later" },
];

export function SoonPage({ code }: { code: string }) {
  const t = useT();
  const item = SOON.find((s) => s.code === code);
  if (!item) {
    return (
      <main className="page page--narrow">
        <div className="pg-notice" role="status">
          <Icon name="info" />
          <div>{t.errors.generic}</div>
        </div>
      </main>
    );
  }
  const text = t.soon.sections[item.code];
  return (
    <main className="page page--narrow soon">
      <header className="page-header">
        <div>
          <p className="soon__status">
            <span className={item.status === "progress" ? "badge badge--accent" : "badge"}>
              {item.status === "progress" ? t.soon.inProgress : t.soon.later}
            </span>
            <span className="soon__scenario">
              {t.soon.scenario} {text.scenario}
            </span>
          </p>
          <h1 className="page-title">
            <Icon name={item.icon} className="soon__icon" />
            {text.title}
          </h1>
          <p className="page-lead">{text.what}</p>
        </div>
      </header>
      <section className="soon__now" aria-label={t.soon.now}>
        <h2 className="section-title">{t.soon.now}</h2>
        <p>{text.now}</p>
        {item.code === "assistant" && (
          <div className="actions">
            <button className="pg-btn pg-btn--secondary" onClick={() => navigate("/read")}>
              <Icon name="book" />
              {t.soon.goReading}
            </button>
          </div>
        )}
      </section>
    </main>
  );
}
