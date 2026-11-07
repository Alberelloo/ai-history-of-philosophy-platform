import { useEffect } from "react";
import { AssistantPanel, takePendingHandoff } from "./AssistantPanel";
import { useT } from "./i18n";

// Страница раздела «Ассистент» (reader-panels.md, 5.10): диалог по всей библиотеке.
// Ссылка из панели книги несёт поручение; вопрос отправляется один раз при первом открытии.
export function AssistantPage() {
  const t = useT();
  useEffect(() => {
    const state = window.history.state as { handoff?: string } | null;
    const pending = state?.handoff ? takePendingHandoff(state.handoff) : null;
    if (pending) {
      // Поручение принято; отправка выполняется AssistantPanel в режиме библиотеки.
      sessionStorage.setItem("philograph:pending-handoff", JSON.stringify(pending));
      window.history.replaceState({ ...state, consumed: true }, "");
    }
  }, []);
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
        />
      </div>
    </main>
  );
}
