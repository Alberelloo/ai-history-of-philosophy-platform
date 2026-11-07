import { useMemo } from "react";
import { AssistantPanel, takePendingHandoff, type PendingHandoff } from "./AssistantPanel";
import { useT } from "./i18n";

// Страница раздела «Ассистент» (reader-panels.md, 5.10): диалог по всей библиотеке.
// Ссылка из панели книги несёт поручение в history.state; вопрос отправляется один раз.
export function AssistantPage({ search = "" }: { search?: string }) {
  const t = useT();
  const pending = useMemo<PendingHandoff | null>(() => {
    const state = window.history.state as { handoff?: string } | null;
    return state?.handoff ? takePendingHandoff(state.handoff) : null;
  }, []);
  const q = useMemo(() => new URLSearchParams(search).get("q") ?? "", [search]);
  return (
    <main className="assistant-page" id="content">
      <div className="assistant-page__col">
        <header className="assistant-page__head">
          <h1 className="pg-display">{t.assistant.label}</h1>
          <p className="assistant-page__subtitle">{t.assistantPage.subtitle}</p>
        </header>
        <AssistantPanel
          mode="library"
          sourceId=""
          selection={null}
          selectionParagraphs={[]}
          onClose={() => {}}
          pending={pending}
          initialQuestion={q || undefined}
        />
      </div>
    </main>
  );
}
