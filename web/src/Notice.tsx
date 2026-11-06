import { useEffect, useRef, useState } from "react";
import { useT } from "./i18n";
import { setScope, useScope } from "./scope";
import { storage, useStored } from "./storage";
import { Generated, Icon, Switch } from "./ui";

// Уведомление при первом входе: как помечено сгенерированное и кто обрабатывает вопросы.
// Версия меняется при существенном изменении текста (например, смене провайдера моделей) —
// тогда уведомление показывается снова.
export const NOTICE_VERSION = "2026-11";
const ATTENTION = "philograph:notice-attention";

export function useNoticeAccepted(): boolean {
  return useStored((s) => s.notice === NOTICE_VERSION);
}

// Ассистент просит показать уведомление, если вопрос задают до его закрытия.
export function requestNotice(): void {
  window.dispatchEvent(new Event(ATTENTION));
}

export function NoticeText() {
  const t = useT();
  return (
    <div className="notice-text">
      <p>{t.notice.about}</p>
      <p>
        {t.notice.markedBefore}{" "}
        <Generated className="card-description ungrounded notice-example">{t.notice.example}</Generated>
        {t.notice.markedAfter}
      </p>
      <p>{t.notice.generationOn}</p>
      <p>{t.notice.provider}</p>
    </div>
  );
}

export function GenerationSettings() {
  const t = useT();
  const scope = useScope();
  return (
    <div className="generation-settings">
      <Switch
        label={t.notice.generation}
        hint={t.notice.generationHint}
        checked={scope.generation}
        onChange={(value) => setScope({ generation: value })}
      />
      <Switch
        label={t.notice.sourcesOnly}
        hint={t.notice.sourcesOnlyHint}
        checked={scope.sourcesOnly}
        onChange={(value) => setScope({ sourcesOnly: value })}
      />
    </div>
  );
}

export function FirstRunNotice() {
  const t = useT();
  const accepted = useNoticeAccepted();
  const [attention, setAttention] = useState(false);
  const box = useRef<HTMLElement>(null);

  useEffect(() => {
    const show = () => {
      setAttention(true);
      box.current?.focus({ preventScroll: true });
      box.current?.scrollIntoView({ block: "nearest" });
    };
    window.addEventListener(ATTENTION, show);
    return () => window.removeEventListener(ATTENTION, show);
  }, []);

  const accept = () => {
    // Сообщение стоит в потоке над страницей: после закрытия текст не должен прыгнуть.
    const height = box.current?.offsetHeight ?? 0;
    const scrolled = window.scrollY > 0;
    storage.acceptNotice(NOTICE_VERSION);
    if (scrolled && height) window.scrollBy(0, -height);
  };

  if (accepted) return null;
  // Сообщение в потоке страницы (Notice): не всплывает и не закрывает контент. Читать можно
  // сразу, а вопрос ассистенту уйдёт только после «Понятно».
  return (
    <section
      ref={box}
      tabIndex={-1}
      className={attention ? "pg-notice first-run attention" : "pg-notice first-run"}
      aria-label={t.notice.label}
    >
      <Icon name="info" />
      <div className="first-run__body">
        <h2 className="first-run__title">{t.notice.title}</h2>
        <NoticeText />
        <GenerationSettings />
      </div>
      <button className="pg-btn pg-btn--ghost pg-btn--sm" onClick={accept}>
        {t.notice.accept}
      </button>
    </section>
  );
}
