import { useEffect, useRef, useState } from "react";
import { setScope, useScope } from "./scope";
import { storage, useStored } from "./storage";

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
  return (
    <div className="notice-text">
      <p>
        PhiloGraph — учебник по истории философии: главы источников, карточки понятий и людей, граф
        происхождения идей и ассистент, который отвечает со ссылками на абзацы.
      </p>
      <p>
        Всё, что модель написала без опоры на источники, помечено значком и рамкой:{" "}
        <span className="card-description ungrounded notice-example">
          <span className="ungrounded-mark" role="img" aria-label="Сгенерировано">
            ◇
          </span>
          пример сгенерированной строки
        </span>
        . Такие строки — подсказка модели, а не установленный факт.
      </p>
      <p>Генерация без опоры на источники включена. Её можно выключить здесь или в настройках.</p>
      <p>
        Вопросы ассистенту, описания карточек и достройку графа обрабатывает внешний провайдер языковых моделей по
        своим правилам. Не пишите в вопросах личные данные.
      </p>
    </div>
  );
}

export function GenerationSettings() {
  const scope = useScope();
  return (
    <div className="generation-settings">
      <label>
        <input
          type="checkbox"
          checked={scope.generation}
          onChange={(e) => setScope({ generation: e.target.checked })}
        />
        Генерация без опоры на источники
      </label>
      <label>
        <input
          type="checkbox"
          checked={scope.sourcesOnly}
          onChange={(e) => setScope({ sourcesOnly: e.target.checked })}
        />
        Только по источникам
      </label>
    </div>
  );
}

export function FirstRunNotice() {
  const accepted = useNoticeAccepted();
  const [attention, setAttention] = useState(false);
  const box = useRef<HTMLElement>(null);

  useEffect(() => {
    const show = () => {
      setAttention(true);
      box.current?.focus();
    };
    window.addEventListener(ATTENTION, show);
    return () => window.removeEventListener(ATTENTION, show);
  }, []);

  if (accepted) return null;
  // Не модальное: читать можно сразу, а вопрос ассистенту уйдёт только после закрытия.
  return (
    <aside
      ref={box}
      tabIndex={-1}
      className={attention ? "first-run attention" : "first-run"}
      role="dialog"
      aria-label="О пометках и обработке вопросов"
    >
      <h2>Прежде чем начать</h2>
      <NoticeText />
      <GenerationSettings />
      <button className="primary" onClick={() => storage.acceptNotice(NOTICE_VERSION)}>
        Понятно
      </button>
    </aside>
  );
}
