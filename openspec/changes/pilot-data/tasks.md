# Tasks

Выделено из `pilot-launch`. В скобках указано, откуда пришла задача. Для каждой задачи указано, что нужно от владельца.

## 1. Источники

- [ ] 1.1 Загрузить одобренные источники каталога: `python -m philograph.library.catalog sync`, затем `status`. В каталоге 304 одобренные записи: 254 первоисточника, 47 учебников, 3 справочника; 76 из них в разделе `epistemology`. Итог (сколько опубликовано, сколько ждут решения, ошибки по шагам) записать в `progress.md` (pilot-launch 1.1). **От владельца:** стенд или сервер с диском под файлы (`PHILOGRAPH_DATABASE_URL`, `PHILOGRAPH_FILES_ROOT`); для смыслового поиска — ключ провайдера эмбеддингов (выбор провайдера — `pilot-evaluation` 1.2).
- [ ] 1.2 Решение по трём черновикам каталога (журнал поиска, проход «Закрытие черновиков»):
  - `gegel-nauka-logiki-t-1-archive`: на archive.org нет издания с текстовым слоем, только DjVu;
  - `rotterdamskiy-pokhvalnoe-slovo-gluposti-ru-wikisource`: издание 1931 г. (Губер, Academia) не найдено ни на ru.wikisource, ни на archive.org;
  - `deduktivnaya-induktivnaya-logika-archive`: тождество переводчика С. А. Котляревского не подтверждено. Если это С. А. Котляревский (1873–1939), он реабилитирован в 1956 г., и защита действует до 31.12.2026.
  
  Каждую запись одобрить или отклонить с доказательством в `review.note`. **От владельца:** решение по лицензии. Для `deduktivnaya-…` его можно отложить до 01.01.2027, когда срок истечёт при любом тождестве.
- [ ] 1.3 Установить переводчиков по электронным каталогам РНБ и РГБ. Из среды агентов они недоступны: РГБ закрывает поиск в robots.txt, НЭБ отдаёт заглушку. Список из журнала поиска:
  - Гегель, «Энциклопедия философских наук» ч. 1–3 (1861–68): «В. П. Чижов»;
  - Фалькенберг, «История новой философии» (1898): В. Иноземцев;
  - Штёкль, «История средневековой философии» (1912): Н. Стрелков и второй переводчик;
  - Гёффдинг, «Философские проблемы» (1904): «Ф. Капелюш», возможно Ф. Д. Капелюш (1876–1945). Это замена исключённой записи `h-ffding-brief-history-modern-philosophy`;
  - Гёффдинг, «Современные философы» (1907): А. Смирнов;
  - ручная проверка уже одобренных записей: Н. Е. Скворцов («Политика», 1865), В. И. Оболенский («О законах», 1827), И. И. Лапшин (ум. 1952, граница срока).
  
  Найденное записать в `sources/catalog.yaml` (новые записи — черновиками) и в `sources/discovery-log.md`. **От владельца:** запрос в каталоги РНБ и РГБ или доступ к ним.
- [ ] 1.4 Решение по условиям CC BY-NC-SA 4.0 для `introduction-to-philosophyweb-pdf` (OpenStax): совместимы ли некоммерческое условие и «share-alike» с моделью продукта (вопрос из пересмотра пробной загрузки). **От владельца:** решение.

## 2. Онтология и упоминания

- [ ] 2.1 Настоящее извлечение онтологии по опубликованным источникам и замер качества по типам связей (add-ontology-filling 1.9; pilot-launch 1.2). Источники вида `public-domain-ru` (`external_processing: false`) наполнение пропускает с причиной `external_processing_forbidden`. Таких одобренных записей 18, из них в разделе `epistemology` две (отмечены *):
  - `aristotle-soul-en-wikisource`*, `berdyaev-poznanie-obshchenie-ru-wikisource`*;
  - `aristotel-politika-ru-wikisource`, `nitsshe-shopengauer-kak-vospitatel-ru-wikisource`, `nitsshe-chelovecheskoe-slishkom-ru-wikisource`, `kerkegor-neschastneyshiy-ru-wikisource`;
  - `berdyaev-russkaya-ideya-ru-wikisource`, `berdyaev-tvorchestvo-obektivatsiya-ru-wikisource`, `berdyaev-samopoznanie-ru-wikisource`, `berdyaev-moe-filosofskoe-mirosozertsanie-ru-wikisource`, `berdyaev-knige-s-l-franka-nepostizhimoe`, `berdyaev-problema-cheloveka-ru-wikisource`, `berdyaev-kharaktere-russkoy-religioznoy-mysli-xix`, `berdyaev-chelovek-mashina-zheleznyy-iron-man`, `berdyaev-personalizm-marksizm-ru-wikisource`;
  - `lyudvigovich-nepostizhimoe-ru-wikisource`, `lyudvigovich-realnost-chelovek-ru-wikisource`, `lyudvigovich-religiya-nauka-ru-wikisource`.
  
  Записать в `progress.md`, сколько утверждений получено по типам связей и какова доля отклонённых проверкой. Для двух источников раздела решить: оставить без утверждений или наполнять вручную оператором. Второй вариант — отдельное изменение. **От владельца:** ключ модели и бюджет наполнения в `config/llm.yaml`.
- [ ] 2.2 Офлайн-разрешение неоднозначных упоминаний моделью (add-entity-mentions-and-cards 1.11; pilot-launch 1.3). У 18 источников из 2.1 разрешение моделью не идёт: упоминание остаётся неоднозначным, событие `knowledge.mentions.unresolved`. Записать долю неразрешённых отдельно для источников с внешней обработкой и без неё. **От владельца:** ключ модели.
