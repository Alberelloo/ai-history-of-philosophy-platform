import { useEffect, useState } from "react";
import { LibraryPage } from "./LibraryPage";
import { ReaderPage } from "./ReaderPage";
import { ParagraphLink } from "./ParagraphLink";

// Адреса: /                   — библиотека
//         /read/:source[/:chapter][#p-<абзац> | #s-<раздел>] — чтение
//         /p/:paragraph       — постоянная ссылка на абзац
export function navigate(path: string): void {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function useLocation(): string {
  const [location, setLocation] = useState(window.location.pathname + window.location.hash);
  useEffect(() => {
    const update = () => setLocation(window.location.pathname + window.location.hash);
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
  const [path, hash = ""] = location.split("#");
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "p" && parts[1]) return <ParagraphLink paragraphId={parts[1]} />;
  if (parts[0] === "read") {
    return <ReaderPage sourceId={parts[1]} chapterId={parts[2]} anchor={hash} />;
  }
  return <LibraryPage />;
}
