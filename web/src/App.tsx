import { useEffect, useState } from "react";
import { AssistantPanel } from "./AssistantPanel";
import { GraphPage } from "./GraphPage";
import { useT } from "./i18n";
import { LibraryPage } from "./LibraryPage";
import { FirstRunNotice } from "./Notice";
import { ParagraphLink } from "./ParagraphLink";
import { ReaderPage } from "./ReaderPage";
import { ReviewPage } from "./ReviewPage";
import { SettingsPage } from "./SettingsPage";
import { Sidebar } from "./Sidebar";
import { SidePanel } from "./SidePanel";
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

// Состояние правой панели живёт выше ReaderPage, чтобы переживать переходы между главами и
// книгами (docs/design/features/reader-panels.md, этап 1). Стек «Назад» появится в этапе 3;
// пока панель хранит один элемент и его содержимое.
export type PanelState = {
  mode: "assistant" | "card";
  sourceId: string;
  selection: string | null;
  selectionParagraphs: string[];
  entityId?: string;
  stripExpanded: boolean;
};

export function App() {
  const t = useT();
  useDocumentAppearance();
  const location = useLocation();
  const [beforeHash, hash = ""] = location.split("#");
  const [path, search = ""] = beforeHash.split("?");
  const parts = path.split("/").filter(Boolean);
  const [panel, setPanel] = useState<PanelState | null>(null);
  return (
    <>
      <Sidebar active={activeItem(parts)} sourceId={parts[0] === "read" ? parts[1] : undefined} panelOpen={panel !== null} />
      {/* Область содержимого: сюда переходит фокус, когда Esc сворачивает боковую панель. */}
      <div id="content" className="app-content" tabIndex={-1}>
        {!storage.persistent() && (
          <div className="pg-notice pg-notice--warning storage-warning" role="status">
            <Icon name="info" />
            <div>{t.app.storageUnavailable}</div>
          </div>
        )}
        <FirstRunNotice />
        <Page parts={parts} search={search} hash={hash} panel={panel} setPanel={setPanel} />
      </div>
      {panel && (
        <SidePanel
          expanded={panel.stripExpanded}
          onExpand={(stripExpanded) => setPanel({ ...panel, stripExpanded })}
          ariaLabel={panel.mode === "assistant" ? t.assistant.label : t.card.label}
        >
          {panel.mode === "assistant" && (
            <AssistantPanel
              sourceId={panel.sourceId}
              selection={panel.selection}
              selectionParagraphs={panel.selectionParagraphs}
              onClose={() => setPanel(null)}
            />
          )}
        </SidePanel>
      )}
    </>
  );
}

function Page({
  parts,
  search,
  hash,
  panel,
  setPanel,
}: {
  parts: string[];
  search: string;
  hash: string;
  panel: PanelState | null;
  setPanel: (panel: PanelState | null) => void;
}) {
  if (parts[0] === "p" && parts[1]) return <ParagraphLink paragraphId={parts[1]} />;
  if (parts[0] === "internal" && parts[1] === "review") return <ReviewPage />;
  if (parts[0] === "settings") return <SettingsPage hash={hash} />;
  if (parts[0] === "soon" && parts[1]) return <SoonPage key={parts[1]} code={parts[1]} />;
  if (parts[0] === "graph" && parts[1]) {
    return <GraphPage key={parts[1]} entityId={parts[1]} query={new URLSearchParams(search)} />;
  }
  if (parts[0] === "read") {
    return (
      <ReaderPage sourceId={parts[1]} chapterId={parts[2]} anchor={hash} panel={panel} setPanel={setPanel} />
    );
  }
  return <LibraryPage />;
}
