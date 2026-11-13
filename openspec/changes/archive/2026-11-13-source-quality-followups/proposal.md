## Why

Пробная загрузка 35 открытых источников (`openspec/changes/archive/*-source-catalog/validation.md`) показала, что конвейер и каталог работают. Но она нашла места, где качество текста и поиска ещё недостаточно для пилота. Их не исправляли в `source-catalog`, чтобы не раздувать изменение.

## What Changes

- Структура цифровых PDF по оглавлению-закладкам (`get_toc`), а не по размеру шрифта.
- Разбор сбоя смыслового поиска (`search.semantic.unavailable`, `ValueError`) во время массовой индексации.
- Разбивка коротких справочных статей на абзацы.
- Адаптеры: год издания для Gutenberg; авторы Wikisource со страниц без шаблона.

## Impact

`src/philograph/library/extract.py`, `parse.py`, `src/philograph/search/*`, адаптеры каталога. Требования уточняются в спецификациях `document-structure` и `paragraph-search`, когда задача будет взята в работу.
