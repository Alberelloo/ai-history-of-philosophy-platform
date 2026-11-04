import { useEffect, useState } from "react";
import { api } from "./api";
import { navigate } from "./App";
import { storage } from "./storage";

function replace(path: string) {
  window.history.replaceState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

// Постоянная ссылка на абзац: открывает его главу, а если абзаца или источника больше нет —
// честно говорит об этом, а не показывает пустую страницу или чужой абзац.
export function ParagraphLink({ paragraphId }: { paragraphId: string }) {
  const [message, setMessage] = useState<string | null>(null);
  const [chapterLink, setChapterLink] = useState<string | null>(null);

  useEffect(() => {
    api.paragraph(paragraphId).then((result) => {
      if (result.status === "found") {
        storage.setCurrentSource(result.source_id);
        replace(`/read/${result.source_id}/${result.chapter_id}#p-${result.paragraph_id}`);
      } else if (result.status === "removed") {
        setMessage("Абзац не найден: в новой версии источника его больше нет.");
        if (result.chapter_id) setChapterLink(`/read/${result.source_id}/${result.chapter_id}`);
      } else if (result.status === "source_unavailable") {
        setMessage("Источник недоступен.");
      } else {
        setMessage("Абзац не найден.");
      }
    });
  }, [paragraphId]);

  if (!message) return <main className="loading">Загрузка…</main>;
  return (
    <main className="reader-problem" role="alert">
      <p>{message}</p>
      {chapterLink && (
        <button className="link" onClick={() => navigate(chapterLink)}>
          Открыть главу, где он был
        </button>
      )}
      <button className="link" onClick={() => navigate("/")}>
        Перейти в библиотеку
      </button>
    </main>
  );
}
