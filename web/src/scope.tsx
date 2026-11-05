import { storage, useStored, type Settings } from "./storage";

// Переключатель источников «только выбранный учебник / все источники» и настройки генерации.
// Значение общее для графа, карточек, ассистента и экрана настроек: изменение в одном месте
// видно в остальных, в том числе в других вкладках.

export type Scope = Settings;

export function setScope(change: Partial<Settings>): void {
  storage.setSettings(change);
}

export function useScope(): Settings {
  return useStored((s) => s.settings);
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
