import { useEffect, useState } from "react";
import { GraphPage } from "./GraphPage";
import { LibraryPage } from "./LibraryPage";
import { ReaderPage } from "./ReaderPage";
import { ParagraphLink } from "./ParagraphLink";
import { ReviewPage } from "./ReviewPage";

// Адреса: /                   — библиотека
//         /read/:source[/:chapter][#p-<абзац> | #s-<раздел>] — чтение
//         /p/:paragraph       — постоянная ссылка на абзац
//         /graph/:entity?recipe=… — граф по запросу
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

export function App() {
  const location = useLocation();
  const [beforeHash, hash = ""] = location.split("#");
  const [path, search = ""] = beforeHash.split("?");
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "p" && parts[1]) return <ParagraphLink paragraphId={parts[1]} />;
  if (parts[0] === "internal" && parts[1] === "review") return <ReviewPage />;
  if (parts[0] === "graph" && parts[1]) {
    return <GraphPage key={parts[1]} entityId={parts[1]} query={new URLSearchParams(search)} />;
  }
  if (parts[0] === "read") {
    return <ReaderPage sourceId={parts[1]} chapterId={parts[2]} anchor={hash} />;
  }
  return <LibraryPage />;
}
