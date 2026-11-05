import { useEffect, useState } from "react";
import { api } from "./api";
import { navigate } from "./App";
import { useT } from "./i18n";
import { storage } from "./storage";
import { Icon } from "./ui";

function replace(path: string) {
  window.history.replaceState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

type Problem = "removed" | "source_unavailable" | "unknown";

// Постоянная ссылка на абзац: открывает его главу, а если абзаца или источника больше нет —
// честно говорит об этом, а не показывает пустую страницу или чужой абзац.
export function ParagraphLink({ paragraphId }: { paragraphId: string }) {
  const t = useT();
  const [problem, setProblem] = useState<Problem | null>(null);
  const [chapterLink, setChapterLink] = useState<string | null>(null);

  useEffect(() => {
    api.paragraph(paragraphId).then((result) => {
      if (result.status === "found") {
        storage.setCurrentSource(result.source_id);
        replace(`/read/${result.source_id}/${result.chapter_id}#p-${result.paragraph_id}`);
      } else if (result.status === "removed") {
        setProblem("removed");
        if (result.chapter_id) setChapterLink(`/read/${result.source_id}/${result.chapter_id}`);
      } else if (result.status === "source_unavailable") {
        setProblem("source_unavailable");
      } else {
        setProblem("unknown");
      }
    });
  }, [paragraphId]);

  if (!problem) return <main className="page loading">{t.app.loading}</main>;
  const message =
    problem === "removed"
      ? t.paragraph.removed
      : problem === "source_unavailable"
        ? t.errors.source_unavailable
        : t.paragraph.notFound;
  return (
    <main className="page page--narrow reader-problem">
      <div className="pg-notice pg-notice--danger" role="alert">
        <Icon name="warning" />
        <div>{message}</div>
      </div>
      <div className="actions">
        {chapterLink && (
          <button className="pg-btn pg-btn--secondary" onClick={() => navigate(chapterLink)}>
            {t.paragraph.openChapter}
          </button>
        )}
        <button className="pg-btn pg-btn--ghost" onClick={() => navigate("/")}>
          {t.app.goLibrary}
        </button>
      </div>
    </main>
  );
}
