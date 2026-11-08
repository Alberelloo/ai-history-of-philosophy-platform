import { useEffect, useState } from "react";
import { GraphPage } from "./GraphPage";
import { useT } from "./i18n";
import { LibraryPage } from "./LibraryPage";
import { FirstRunNotice } from "./Notice";
import { ParagraphLink } from "./ParagraphLink";
import { ReaderPage } from "./ReaderPage";
import { ReviewPage } from "./ReviewPage";
import { SettingsPage } from "./SettingsPage";
import { Sidebar } from "./Sidebar";
import { SoonPage } from "./SoonPage";
import { storage } from "./storage";
import { useDocumentAppearance } from "./theme";
import { Icon } from "./ui";

// Адреса: /                   — библиотека
//         /read/:source[/:chapter][#p-<абзац> | #s-<раздел>] — чтение
//         /p/:paragraph       — постоянная ссылка на абзац
//         /graph/:entity?recipe=… — граф по запросу
//         /settings[#раздел]  — настройки читателя
//         /soon/:раздел       — раздел в разработке
export function navigate(path: string): void {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function useLocation(): string {
  const current = () => window.location.pathname + window.location.search + window.location.hash;
  const [location, setLocation] = useState(current);
  useEffect(() => {
    const update = () => setLocation(current());
    window.addEventListener("popstate", update);
    window.addEventListener("hashchange", update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener("hashchange", update);
    };
  }, []);
  return location;
}

// Какой пункт боковой панели отметить.
function activeItem(parts: string[]): string {
  if (parts.length === 0) return "library";
  if (parts[0] === "read" || parts[0] === "p") return "reading";
  if (parts[0] === "soon") return parts[1] ?? "other";
  if (parts[0] === "settings" || parts[0] === "graph") return parts[0];
  return "other";
}

export function App() {
  const t = useT();
  useDocumentAppearance();
  const location = useLocation();
  const [beforeHash, hash = ""] = location.split("#");
  const [path, search = ""] = beforeHash.split("?");
  const parts = path.split("/").filter(Boolean);
  return (
    <>
      <Sidebar active={activeItem(parts)} sourceId={parts[0] === "read" ? parts[1] : undefined} />
      {/* Область содержимого: сюда переходит фокус, когда Esc сворачивает боковую панель. */}
      <div id="content" className="app-content" tabIndex={-1}>
        {!storage.persistent() && (
          <div className="pg-notice pg-notice--warning storage-warning" role="status">
            <Icon name="info" />
            <div>{t.app.storageUnavailable}</div>
          </div>
        )}
        <FirstRunNotice />
        <Page parts={parts} search={search} hash={hash} />
      </div>
    </>
  );
}

function Page({ parts, search, hash }: { parts: string[]; search: string; hash: string }) {
  if (parts[0] === "p" && parts[1]) return <ParagraphLink paragraphId={parts[1]} />;
  if (parts[0] === "internal" && parts[1] === "review") return <ReviewPage />;
  if (parts[0] === "settings") return <SettingsPage hash={hash} />;
  if (parts[0] === "soon" && parts[1]) return <SoonPage key={parts[1]} code={parts[1]} />;
  if (parts[0] === "graph" && parts[1]) {
    return <GraphPage key={parts[1]} entityId={parts[1]} query={new URLSearchParams(search)} />;
  }
  if (parts[0] === "read") {
    return <ReaderPage sourceId={parts[1]} chapterId={parts[2]} anchor={hash} />;
  }
  return <LibraryPage />;
}
