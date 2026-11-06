import { useT } from "./i18n";
import { storage, useStored, type Settings } from "./storage";
import { Switch } from "./ui";

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
  const t = useT();
  const scope = useScope();
  return (
    <span className="scope-toggle">
      <Switch
        label={t.scope.onlyTextbook}
        checked={scope.onlyTextbook && Boolean(textbook)}
        disabled={!textbook}
        title={textbook ? undefined : t.scope.chooseFirst}
        onChange={(value) => setScope({ onlyTextbook: value })}
      />
    </span>
  );
}
