import { useEffect, useState } from "react";

// Переключатель источников «только выбранный учебник / все источники» и достройка моделью.
// Значение общее для графа, карточек и ассистента: изменение в одном месте видно в остальных,
// в том числе в других вкладках. Без хранилища (приватный режим) живёт до закрытия вкладки.

const KEY = "philograph:scope:v1";
const EVENT = "philograph:scope";

export type Scope = { onlyTextbook: boolean; generation: boolean };

const defaults: Scope = { onlyTextbook: false, generation: true };
let memory: Scope = defaults;

function read(): Scope {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? { ...defaults, ...(JSON.parse(raw) as Partial<Scope>) } : memory;
  } catch {
    return memory;
  }
}

export function setScope(change: Partial<Scope>): void {
  memory = { ...read(), ...change };
  try {
    window.localStorage.setItem(KEY, JSON.stringify(memory));
  } catch {
    // хранилище недоступно: значение остаётся в памяти вкладки
  }
  window.dispatchEvent(new Event(EVENT));
}

export function useScope(): Scope {
  const [scope, set] = useState<Scope>(read);
  useEffect(() => {
    const update = () => set(read());
    window.addEventListener(EVENT, update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener(EVENT, update);
      window.removeEventListener("storage", update);
    };
  }, []);
  return scope;
}

export function ScopeToggle({ textbook }: { textbook?: string }) {
  const scope = useScope();
  return (
    <label className="scope-toggle" title={textbook ? undefined : "Сначала выберите учебник в библиотеке"}>
      <input
        type="checkbox"
        checked={scope.onlyTextbook && Boolean(textbook)}
        disabled={!textbook}
        onChange={(e) => setScope({ onlyTextbook: e.target.checked })}
      />
      Только выбранный учебник
    </label>
  );
}
