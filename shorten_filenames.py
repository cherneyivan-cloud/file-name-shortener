import sys
import os

# Создаём отладочный лог при старте
try:
    with open("startup_debug.log", "w", encoding='utf-8') as f:
        f.write("Скрипт запущен\n")
except:
    pass

# Глобальный перехват всех исключений
try:
    import re
    import time
    import json
    import traceback
    import tempfile
    import ctypes
    from ctypes import wintypes
    from pathlib import Path
    from collections import defaultdict

    # Константы для Windows API
    MOVEFILE_REPLACE_EXISTING = 0x1
    MOVEFILE_WRITE_THROUGH = 0x8

    # Загрузка kernel32
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.MoveFileW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        kernel32.MoveFileW.restype = wintypes.BOOL
    except Exception:
        kernel32 = None

    # Путь к пользовательским правилам
    CUSTOM_RULES_FILE = "custom_rules.json"
    CUSTOM_RULES = []

    # Максимальная длина имени после сокращения (включая расширение)
    MAX_FINAL_NAME_LEN = 80
    # Порог для предупреждения о длинном полном пути
    MAX_FULL_PATH_LEN = 250

    # ---------- Вспомогательные функции для длинных путей ----------
    def get_win32_long_path_str(path_str: str) -> str:
        if sys.platform != 'win32':
            return path_str
        if path_str.startswith('\\\\?\\'):
            return path_str
        if path_str.startswith('\\\\'):
            return '\\\\?\\UNC\\' + path_str[2:]
        else:
            return '\\\\?\\' + path_str

    def strip_long_prefix(path_str: str) -> str:
        r"""Удаляет префикс \\?\ или \\?\UNC\ для получения обычного пути."""
        if path_str.startswith('\\\\?\\UNC\\'):
            return '\\\\' + path_str[8:]
        elif path_str.startswith('\\\\?\\'):
            return path_str[4:]
        else:
            return path_str

    def walk_long(root_path: str):
        result = []
        root_path = get_win32_long_path_str(root_path)
        try:
            with os.scandir(root_path) as it:
                for entry in it:
                    if entry.name.startswith('.'):
                        continue
                    result.append(entry.path)
                    if entry.is_dir():
                        result.extend(walk_long(entry.path))
        except Exception as e:
            print(f"Ошибка при обходе {root_path}: {e}")
        return result

    # ---------- Загрузка/сохранение правил ----------
    def load_custom_rules():
        global CUSTOM_RULES
        if os.path.exists(CUSTOM_RULES_FILE):
            try:
                with open(CUSTOM_RULES_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    CUSTOM_RULES = [(item['original'], item['replacement']) for item in data]
            except Exception:
                CUSTOM_RULES = []
        else:
            CUSTOM_RULES = []

    def save_custom_rules(rules):
        data = [{'original': orig, 'replacement': repl} for orig, repl in rules]
        with open(CUSTOM_RULES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_custom_rules_interactive():
        print("Режим добавления новых сокращений.")
        print("Введите слово или фразу для замены (или пустую строку для завершения).")
        while True:
            orig = input("Введите слово или фразу для замены: ").strip()
            if not orig:
                break
            repl = input("Введите сокращение: ").strip()
            if not repl:
                print("Сокращение не может быть пустым. Попробуйте снова.")
                continue
            existing = [r for r in CUSTOM_RULES if r[0].lower() == orig.lower()]
            if existing:
                print(f"Правило для '{orig}' уже существует (замена: {existing[0][1]}).")
                overwrite = input("Перезаписать? (y/n): ").strip().lower()
                if overwrite != 'y':
                    continue
                CUSTOM_RULES[:] = [r for r in CUSTOM_RULES if r[0].lower() != orig.lower()]
            confirm = input(f"Добавить правило '{orig}' -> '{repl}'? (y/n): ").strip().lower()
            if confirm == 'y':
                CUSTOM_RULES.append((orig, repl))
                print("Правило добавлено.")
            else:
                print("Правило не добавлено.")
        if CUSTOM_RULES:
            save_custom_rules(CUSTOM_RULES)
            print(f"Сохранено {len(CUSTOM_RULES)} правил.")
        else:
            print("Ничего не сохранено.")

    # ---------- Встроенные правила (обновлены) ----------
    BUILTIN_REPLACEMENTS = {
        # Новые правила (применяются первыми)
        r'Ведомость_верха_кон_слоев_дор_одежды': 'Вв_КДО',
        r'Нижний_слой_основания_слой': 'нсос',
        r'Верхний_слой_основания': 'всс',
        r'Верхний_слой': 'вс',
        r'Картограммы_планировки_территорий': 'карт_план_тер',
        r'Сводный_план_': 'СП',
        r'_Внешние_ссылки': 'вс',
        r'Конструкция_дор_одежды': 'КДО',
        r'Разбивочный_чертёж': 'РЧ',
        r'Временная_металлическая_труба': 'ВМТ',
        r'Планировки': 'П',
        r'Укрепления': 'Ук',
        r'Территории': 'тер',
        r'оформление': 'оф',          # заменяет "Оформление" -> "ОФ"
        r'покр': 'п',
        r'Съезд': 'с',
        r'Попикетная': 'П',
        # Старые правила (кроме "Оформление", т.к. заменено)
        r'\bСтроительство\b': 'стр-во',
        r'\bСтроительства\b': 'стр-ва',
        r'\bПереустройство\b': 'пер-во',
        r'\bназначения\b': 'назн',
        r'Общие\s+данные': 'ОД',
        r'\bасфальтобетон\b': 'аб',
        r'\bВедомость\b': 'В',
        r'\bВедомости\b': 'В',
        r'\bДорожной\b': 'дор',
        r'\bКонструктивных\b': 'кон',
        r'Раздел\s*№\s*(\d+)': r'Р\1',
        r'Подраздел\s*№\s*(\d+)': r'П\1',
        r'Часть\s*№\s*(\d+)': r'Ч\1',
        r'Книга\s*№\s*(\d+)': r'К\1',
        r'\(изм\.\s*(\d+)\)': r'И\1',
        r'Изм\.\s*(\d+)': r'И\1',
        r'\bВнешние_ссылки\b': 'ВС',
        r'\bБазовый_комплект\b': 'БК',
        r'\bЭлектроснабжение\b': 'ЭН',
        r'Сводный\s+план': 'СП',
        r'Сводный_план': 'СП',
        r'\s+': '_',
        r'№': '#',
        r'[^\w\-._#]': '',
    }

    # ---------- Сокращение и усечение имени ----------
    def truncate_name(name: str, max_len: int) -> str:
        """Обрезает имя до указанной длины, сохраняя расширение (если есть)."""
        if '.' in name and not name.endswith('.'):
            base, ext = os.path.splitext(name)
        else:
            base, ext = name, ''
        if len(base) <= max_len:
            return name
        new_base = base[:max_len]
        # Стараемся обрезать по разделителю для читаемости
        for sep in ('_', '-'):
            if sep in new_base:
                new_base = new_base.rsplit(sep, 1)[0]
                break
        return new_base + ext

    def shorten_name(name: str, is_dir: bool = False) -> str:
        """Применяет правила сокращения и усекает до MAX_FINAL_NAME_LEN (80 символов)."""
        if is_dir:
            base = name
            ext = ''
        else:
            if '.' in name and not name.endswith('.'):
                base, ext = os.path.splitext(name)
            else:
                base, ext = name, ''

        new_base = base
        for orig, repl in CUSTOM_RULES:
            new_base = re.sub(re.escape(orig), repl, new_base, flags=re.IGNORECASE)
        for pattern, repl in BUILTIN_REPLACEMENTS.items():
            new_base = re.sub(pattern, repl, new_base, flags=re.IGNORECASE)

        new_base = new_base.replace('.', '_')
        new_base = re.sub(r'_+', '_', new_base)
        new_base = re.sub(r'-+', '-', new_base)
        new_base = new_base.strip('_.-')

        # Обязательное усечение до 80 символов
        full_name = new_base + ext
        return truncate_name(full_name, MAX_FINAL_NAME_LEN)

    def get_unique_path(target_path: Path, occupied: set = None) -> Path:
        if not target_path.exists() and (occupied is None or target_path not in occupied):
            return target_path
        parent = target_path.parent
        stem = target_path.stem if target_path.suffix else target_path.name
        ext = target_path.suffix
        counter = 2
        while True:
            new_name = f"{stem}_{counter}{ext}"
            # Убедимся, что новое имя тоже не превышает лимит
            new_name = truncate_name(new_name, MAX_FINAL_NAME_LEN)
            new_path = parent / new_name
            if not new_path.exists() and (occupied is None or new_path not in occupied):
                return new_path
            counter += 1

    # ---------- Запись лога с резервными файлами ----------
    def write_log(log_file: str, log_entries: list) -> None:
        """Записывает лог без падений. Если основной файл занят другим процессом
        (открыт в Блокноте/Excel), пробует rename_log_1.txt, rename_log_2.txt, ...,
        затем %TEMP%\\rename_log.txt. Если заняты все варианты — выводит лог в консоль."""
        content = "\n".join(log_entries)
        base_dir = os.path.dirname(os.path.abspath(log_file))
        base_name = os.path.basename(log_file)
        stem, ext = os.path.splitext(base_name)

        candidates = [log_file]
        for i in range(1, 20):
            candidates.append(os.path.join(base_dir, f"{stem}_{i}{ext}"))
        candidates.append(os.path.join(tempfile.gettempdir(), base_name))

        for candidate in candidates:
            try:
                with open(candidate, 'w', encoding='utf-8') as f:
                    f.write(content)
                if candidate != log_file:
                    print(f"ВНИМАНИЕ: {log_file} занят другим процессом. Лог сохранён в {candidate}")
                return
            except OSError:
                continue

        print("НЕ УДАЛОСЬ записать лог-файл ни в один из вариантов. Содержимое лога:")
        print(content)

    # ---------- Безопасное переименование ----------
    def safe_rename_with_retry(old_path: Path, new_path: Path, occupied: set, max_retries: int = 3) -> tuple:
        parent = new_path.parent
        if not parent.exists():
            return (False, new_path, f"Родительская папка не существует: {parent}")
        if not os.access(str(parent), os.W_OK):
            return (False, new_path, f"Нет прав на запись в родительскую папку: {parent}")

        actual_new = new_path
        if new_path.exists() and new_path != old_path:
            actual_new = get_unique_path(new_path, occupied)
            occupied.add(actual_new)

        old_abs = str(old_path.resolve())
        new_abs = str(actual_new.resolve())

        for attempt in range(max_retries):
            try:
                if kernel32 is not None:
                    if old_abs.startswith('\\\\?'):
                        old_long = old_abs
                    elif old_abs.startswith('\\\\'):
                        old_long = '\\\\?\\UNC\\' + old_abs[2:]
                    else:
                        old_long = '\\\\?\\' + old_abs

                    if new_abs.startswith('\\\\?'):
                        new_long = new_abs
                    elif new_abs.startswith('\\\\'):
                        new_long = '\\\\?\\UNC\\' + new_abs[2:]
                    else:
                        new_long = '\\\\?\\' + new_abs

                    result = kernel32.MoveFileW(old_long, new_long)
                    if result:
                        return (True, actual_new, "")
                    error_code = ctypes.get_last_error()
                    if error_code in (5, 32) and attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    return (False, actual_new, f"MoveFileW ошибка {error_code}")
                else:
                    os.rename(old_abs, new_abs)
                    return (True, actual_new, "")
            except OSError as e:
                if e.winerror in (5, 32) and attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return (False, actual_new, str(e))
            except Exception as e:
                return (False, actual_new, str(e))
        return (False, actual_new, "Превышено число попыток")

    # ---------- Основная функция ----------
    def rename_items(root_dir: str, auto_apply: bool = False, dry_run: bool = False, log_file: str = "rename_log.txt"):
        start_time = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entries = []
        log_entries.append(f"=== Запуск {start_time} ===")
        log_entries.append(f"Корневая папка: {root_dir}")

        try:
            print("Выполняется обход каталога...")
            item_paths = walk_long(root_dir)
            if not item_paths:
                msg = "Не найдено элементов для обработки (возможно, папка пуста или ошибка доступа)."
                print(msg)
                log_entries.append(msg)
                write_log(log_file, log_entries)
                wait_exit()
                return

            items = [Path(p) for p in item_paths]
            log_entries.append(f"Найдено элементов: {len(items)}")
            print(f"Найдено элементов: {len(items)}")

            items.sort(key=lambda p: len(p.parts), reverse=True)

            conflict_map = defaultdict(list)
            for old_path in items:
                is_dir = old_path.is_dir()
                new_name = shorten_name(old_path.name, is_dir)
                new_path = old_path.parent / new_name
                if new_path == old_path:
                    continue
                conflict_map[new_path].append(old_path)

            final_changes = []
            occupied = set()
            for new_path, sources in conflict_map.items():
                if len(sources) == 1:
                    final_changes.append((sources[0], new_path))
                    occupied.add(new_path)
                else:
                    for idx, src in enumerate(sources, start=1):
                        unique_new = get_unique_path(new_path, occupied)
                        final_changes.append((src, unique_new))
                        occupied.add(unique_new)

            if not final_changes:
                msg = "Все имена уже соответствуют правилам сокращения. Изменений не требуется."
                print(msg)
                log_entries.append(msg)
                write_log(log_file, log_entries)
                wait_exit()
                return

            final_changes.sort(key=lambda x: len(x[0].parts), reverse=True)

            # Вывод списка изменений
            print(f"\nБудет переименовано {len(final_changes)} элементов:\n")
            log_entries.append(f"Будет переименовано {len(final_changes)} элементов:")

            root_normal = strip_long_prefix(root_dir)
            for old, new in final_changes:
                old_str = strip_long_prefix(str(old))
                new_str = strip_long_prefix(str(new))
                try:
                    rel_old = os.path.relpath(old_str, root_normal)
                    rel_new = os.path.relpath(new_str, root_normal)
                except ValueError:
                    rel_old = old_str
                    rel_new = new_str
                print(f"  {rel_old}  ->  {rel_new}")
                log_entries.append(f"  {rel_old}  ->  {rel_new}")

            # Проверка на слишком длинные полные пути (даже при коротком имени)
            long_path_items = []
            for idx, (old, new) in enumerate(final_changes):
                if len(str(new)) > MAX_FULL_PATH_LEN:
                    long_path_items.append(idx)

            if long_path_items and not auto_apply and not dry_run:
                print(f"\nВнимание: {len(long_path_items)} элементов имеют полный путь длиннее {MAX_FULL_PATH_LEN} символов.")
                print("Это может вызвать ошибки при переименовании в Windows.")
                answer = input("Продолжить? (y/n): ").strip().lower()
                if answer != 'y':
                    msg = "Операция отменена пользователем."
                    print(msg)
                    log_entries.append(msg)
                    write_log(log_file, log_entries)
                    wait_exit()
                    return

            if dry_run:
                print("\n[РЕЖИМ ПРЕДПРОСМОТРА] Изменения НЕ применяются.")
                print(f"Будет переименовано: {len(final_changes)} элементов.")
                log_entries.append("[РЕЖИМ ПРЕДПРОСМОТРА] Изменения не применялись.")
                write_log(log_file, log_entries)
                wait_exit()
                return
            if auto_apply:
                print("\n[АВТОМАТИЧЕСКАЯ ОБРАБОТКА] Применяем изменения без подтверждения.")
                log_entries.append("[АВТОМАТИЧЕСКАЯ ОБРАБОТКА]")
            else:
                answer = input("\nПрименить изменения? (y/n): ").strip().lower()
                if answer != 'y':
                    msg = "Операция отменена пользователем."
                    print(msg)
                    log_entries.append(msg)
                    write_log(log_file, log_entries)
                    wait_exit()
                    return

            # Выполняем переименование
            renamed_count = 0
            errors = []
            for old, new in final_changes:
                success, actual_new, err_msg = safe_rename_with_retry(old, new, occupied)
                if success:
                    renamed_count += 1
                    log_entries.append(f"УСПЕШНО: {old} -> {actual_new}")
                else:
                    error_msg = f"ОШИБКА при {old} -> {actual_new}: {err_msg}"
                    print(error_msg)
                    log_entries.append(error_msg)
                    errors.append((strip_long_prefix(str(old)), strip_long_prefix(str(actual_new)), err_msg))

            # Итоговый отчёт
            print(f"\n{'='*60}")
            print(f"Обработка завершена.")
            print(f"Успешно переименовано: {renamed_count} из {len(final_changes)} элементов.")
            if errors:
                print(f"Ошибок: {len(errors)}")
                print("\nСписок элементов, которые не удалось переименовать:")
                for old, new, err in errors:
                    print(f"  {old}  ->  {new}")
                    print(f"    Причина: {err}")
                print("\nВозможные причины ошибок:")
                print("  - Файл/папка открыт в другой программе (проводник, AutoCAD и т.п.)")
                print("  - Недостаточно прав на запись в целевой каталог")
                print("  - Полный путь слишком длинный (превышает ограничение Windows)")
                print("  - Антивирус или сетевая политика блокируют операцию")
                print("\nРекомендации:")
                print("  - Закройте все программы, которые могут использовать эти файлы")
                print("  - Проверьте права доступа к папке")
                log_entries.append("\n--- СПИСОК ОШИБОК ---")
                for old, new, err in errors:
                    log_entries.append(f"ОШИБКА: {old} -> {new} : {err}")
            else:
                print("Все элементы переименованы успешно!")

            write_log(log_file, log_entries)

        except Exception as e:
            error_msg = f"КРИТИЧЕСКАЯ ОШИБКА: {e}\n{traceback.format_exc()}"
            print(error_msg)
            log_entries.append(error_msg)
            write_log(log_file, log_entries)
            wait_exit()
            raise

        wait_exit()

    def wait_exit():
        input("\nНажмите Enter для выхода...")

    def show_menu():
        print("\n" + "="*60)
        print("  ПРОГРАММА АВТОМАТИЧЕСКОГО СОКРАЩЕНИЯ ИМЁН ФАЙЛОВ И ПАПОК")
        print("="*60)
        print("Выберите режим работы:")
        print("  1. Добавить новые сокращения (пользовательские правила)")
        print("  2. Предварительный просмотр (только показать изменения)")
        print("  3. Интерактивный режим (показать изменения и запросить подтверждение)")
        print("  4. Автоматическая обработка (применить все изменения без запросов)")
        print("  0. Выход")
        print("="*60)

    def get_path_from_user():
        path = input("\nВведите путь к корневой папке: ").strip()
        if not path:
            print("Путь не может быть пустым.")
            return None
        return path

    # ---------- Точка входа ----------
    if __name__ == "__main__":
        load_custom_rules()
        args = sys.argv[1:]

        if args:
            auto_apply = False
            dry_run = False
            root_path = None

            if '--add' in args or '-add' in args:
                add_custom_rules_interactive()
                sys.exit(0)

            if '--dry-run' in args or '-n' in args:
                dry_run = True
                args = [a for a in args if a not in ('--dry-run', '-n')]

            if '--apply' in args or '-a' in args:
                auto_apply = True
                args = [a for a in args if a not in ('--apply', '-a')]

            if args:
                root_path = args[0]
            else:
                root_path = input("Введите путь к корневой папке: ").strip()

            if root_path:
                rename_items(root_path, auto_apply=auto_apply, dry_run=dry_run)
            else:
                print("Путь не указан. Завершение.")
                wait_exit()
            sys.exit(0)

        # Интерактивное меню
        while True:
            show_menu()
            choice = input("Ваш выбор (0-4): ").strip()
            if choice == '0':
                print("Выход.")
                break
            elif choice == '1':
                add_custom_rules_interactive()
                continue
            elif choice == '2':
                path = get_path_from_user()
                if path:
                    rename_items(path, auto_apply=False, dry_run=True)
                continue
            elif choice == '3':
                path = get_path_from_user()
                if path:
                    rename_items(path, auto_apply=False, dry_run=False)
                continue
            elif choice == '4':
                path = get_path_from_user()
                if path:
                    rename_items(path, auto_apply=True, dry_run=False)
                continue
            else:
                print("Неверный ввод. Пожалуйста, выберите 0-4.")
                continue
            break

except Exception as e:
    error_text = f"КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}\n{traceback.format_exc()}"
    try:
        with open("rename_log.txt", "w", encoding='utf-8') as f:
            f.write(error_text)
    except:
        pass
    print(error_text)
    input("\nНажмите Enter для выхода...")
    sys.exit(1)