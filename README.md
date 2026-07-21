# LLM Fight Club
Арена, на которой LLM-модели спорят друг с другом, а судьи-LLM оценивают их логику.

## Установка
Для работы программы нужен [uv](https://docs.astral.sh/uv/) — он сам скачает нужную версию Python и все зависимости. Ничего ставить вручную не нужно.

### 1. Установите uv
**Windows** (PowerShell):
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
После установки закройте и снова откройте терминал, чтобы команда `uv` стала доступна.

### 2. Скачайте проект
```bash
git clone <адрес-репозитория>
cd llm-fight-club
```

### 3. Установите все зависимости
В папке проекта выполните одну команду:
```bash
uv sync
```

`uv sync` сам создаст виртуальное окружение, поставит Python 3.14 и все библиотеки из `pyproject.toml`. Готово.

## Запуск
Все команды запускаются через `uv run`, чтобы использовать установленное окружение.

### Запустить бой по конфигу
```bash
uv run python -m fightclub run config/sample.toml
```

### Запустить все бои из папки
```bash
uv run python -m fightclub batch config
```

### Запустить веб-дашборд
```bash
uv run python -m dashboard
```
Откройте в браузере `http://127.0.0.1:8000`.

## Конфиги
Примеры конфигов лежат в папке `config/`:

- `sample.toml` — бой через локальную Ollama.
- `sample_api.toml` — бой через API OpenAI / Anthropic (нужны API-ключи).

Скопируйте нужный пример, отредактируйте модели и `base_url` под себя.
