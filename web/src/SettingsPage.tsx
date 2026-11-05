import { useState } from "react";
import { navigate } from "./App";
import { GenerationSettings, NoticeText } from "./Notice";
import { setScope, useScope } from "./scope";
import { storage } from "./storage";

// Настройки читателя. Хранятся только в этом браузере и уходят с каждым запросом.
export function SettingsPage() {
  const scope = useScope();
  const [confirming, setConfirming] = useState(false);
  const [done, setDone] = useState(false);

  return (
    <main className="settings">
      <button className="link" onClick={() => navigate("/")}>
        ← Библиотека
      </button>
      <h1>Настройки</h1>
      <section aria-label="Генерация">
        <h2>Ответы и карточки</h2>
        <GenerationSettings />
        <p className="muted">
          Без генерации граф не достраивается моделью, карточки показываются без описаний модели, а ассистент
          показывает только то, что подтверждено источниками.
        </p>
      </section>
      <section aria-label="Источники">
        <h2>Источники</h2>
        <label>
          <input type="radio" name="scope" checked={!scope.onlyTextbook} onChange={() => setScope({ onlyTextbook: false })} />
          Все источники
        </label>
        <label>
          <input type="radio" name="scope" checked={scope.onlyTextbook} onChange={() => setScope({ onlyTextbook: true })} />
          Только выбранный учебник
        </label>
      </section>
      <details>
        <summary>О пометках и обработке вопросов</summary>
        <NoticeText />
      </details>
      <section aria-label="Данные браузера">
        <h2>Данные в этом браузере</h2>
        <p className="muted">Настройки, места чтения и диалоги с ассистентом хранятся только здесь.</p>
        {!confirming && (
          <button onClick={() => (setDone(false), setConfirming(true))}>Сбросить все данные</button>
        )}
        {confirming && (
          <div role="alertdialog" aria-label="Подтверждение сброса" className="confirm">
            <p>Удалить настройки, места чтения и диалоги в этом браузере? Отменить это нельзя.</p>
            <button
              className="primary"
              onClick={() => {
                storage.reset();
                setConfirming(false);
                setDone(true);
              }}
            >
              Удалить
            </button>{" "}
            <button onClick={() => setConfirming(false)}>Отмена</button>
          </div>
        )}
        {done && <p role="status">Данные удалены.</p>}
      </section>
    </main>
  );
}
