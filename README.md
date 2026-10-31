# PokerNow Analyst

Windows Python/Tkinter-приложение и распакованное расширение Opera/Chromium.

Проект восстановлен из доступного архива v8. Версия 8.1.0 добавляет обновление
через GitHub Releases, отдельный updater, проверки ZIP/SHA-256 и резервное копирование.
Недоступные исходники v9–v11 не выдаются за восстановленные.

- [Установка, обновление и восстановление](DELIVERY_RU.md)
- [Описание исходной v8](README_RU.md)
- [Изменения текущего выпуска](RELEASE_NOTES.md)
- Релизы: https://github.com/hsvea/pokernow-analyst/releases

Данные остаются локально в `%APPDATA%\PokerNowAnalyst`. GitHub-токены в приложение
не включаются. Загрузка обновления начинается только после подтверждения пользователя.

Исходный код: Python 3.12+, `python app.py`. Тесты:
`python -m unittest discover -s tests -v`. Сборка Windows: `BUILD_EXE_WINDOWS.bat`.

Интеграция Codex в исходной v8 опциональна и требует отдельного SDK; базовая EXE-сборка
не включает его. Локальный анализ и работа с историей не требуют SDK.

