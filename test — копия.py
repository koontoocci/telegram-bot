import json
import datetime
import logging
import qrcode
import io
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters


# Инициализация базы данных
DATABASE_FILE = 'products.json'
SETTINGS_FILE = 'settings.json'
DATA_FILE = "scheduler_data.json"
LOG_FILE = "scheduler_logs.json"
TOPIC_IDS = {
    "products_management": 2,  # ID топика для /add, /list, /edit, /delete и уведомлений
    "pc_and_notifications": 31,  # ID топика для /pc, /check_on, /check_off
    "feedback": 3428,  # ID топика для обратной связи
}
HELP_TEXT_FILE = 'help_text.md'
last_feedback_time = {}

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Шаги для обратной связи
ASK_NAME, ASK_FEEDBACK, ASK_RESPONSE_NEEDED = range(3)

# Чтение и запись данных в файл
def load_data():
    try:
        with open(DATABASE_FILE, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        logger.warning(f"Файл {DATABASE_FILE} не найден, создается новый.")
        return {'products': []}
    except json.JSONDecodeError:
        logger.error(f"Ошибка при чтении JSON из файла {DATABASE_FILE}.")
        return {'products': []}

def save_data(data):
    try:
        with open(DATABASE_FILE, 'w') as file:
            json.dump(data, file, indent=4)
        logger.info(f"Данные успешно сохранены в {DATABASE_FILE}.")
    except Exception as e:
        logger.error(f"Ошибка при записи данных в файл {DATABASE_FILE}: {e}")

# Чтение настроек из JSON
def load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"notifications_enabled": True}  # Уведомления включены по умолчанию

# Сохранение настроек в JSON
def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as file:
        json.dump(settings, file, indent=4)

# Helper functions
def load_scheduler_data():
    try:
        with open(DATA_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"tasks": [], "last_id": 0}

def save_scheduler_data(data):
    with open(DATA_FILE, "w") as file:
        json.dump(data, file, indent=4)

def load_logs():
    try:
        with open(LOG_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"logs": []}

def save_logs(logs):
    with open(LOG_FILE, "w") as file:
        json.dump(logs, file, indent=4)

async def check_expirations(context: ContextTypes.DEFAULT_TYPE):
    allowed_chat_id = -1002151355212
    data = load_data()
    expired_products = []
    current_time = datetime.datetime.now()

    for product in data['products']:
        expiry_time = datetime.datetime.fromisoformat(product['expiry_date'])
        if expiry_time <= current_time:
            expired_products.append(product)
            # Уведомление пользователю о просроченном товаре
            await send_expiration_notification(product, context, allowed_chat_id)

    # Удаляем просроченные товары
    data['products'] = [product for product in data['products'] if product not in expired_products]
    save_data(data)

# Отправка уведомления о просроченном товаре
async def send_expiration_notification(product, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    thread_id = TOPIC_IDS["products_management"]
    expiry_date = datetime.datetime.fromisoformat(product['expiry_date']).strftime("%d.%m.%Y %H:%M")
    message = f"Товар просрочен: {product['name']}, дата и время: {expiry_date}"
    await context.bot.send_message(chat_id=chat_id, text=message, message_thread_id=thread_id)

# Команда /add — добавление товара
async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed_chat_id = -1002151355212
    required_topic_id = TOPIC_IDS["products_management"]

    # Проверка чата и темы
    if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != required_topic_id:
        await update.message.reply_text("Эта команда доступна только в теме 'Списания'.")
        return

    try:
        logger.info(f"Получены аргументы: {context.args}")

        if len(context.args) < 3:
            await update.message.reply_text(
                "Пожалуйста, укажите названия товаров (через запятую), дату и время истечения срока."
            )
            return

        # Соединяем аргументы обратно в строку
        full_input = " ".join(context.args)

        # Разделяем товары и дату/время
        *names_part, date_part, time_part = full_input.split()
        names_string = " ".join(names_part)

        # Разделяем товары по запятой
        names = [name.strip() for name in names_string.split(",") if name.strip()]
        if not names:
            await update.message.reply_text("Ошибка: укажите хотя бы одно название товара.")
            return

        # Преобразование формата даты и времени
        try:
            date_object = datetime.datetime.strptime(f"{date_part} {time_part}", "%d.%m.%Y %H:%M")
            expiry_date = date_object.isoformat()  # Преобразование в формат ISO 8601
        except ValueError as e:
            logger.error(f"Ошибка преобразования даты: {e}")
            await update.message.reply_text("Неверный формат даты. Используйте формат 'DD.MM.YYYY HH:MM'.")
            return

        # Проверка, что дата в будущем
        if date_object <= datetime.datetime.now():
            await update.message.reply_text("Ошибка: дата и время не могут быть в прошлом.")
            return

        # Загрузка данных
        data = load_data()

        # Добавление каждого товара
        for name in names:
            product_id = len(data['products']) + 1
            data['products'].append({
                'id': product_id,
                'name': name,
                'expiry_date': expiry_date
            })

        # Сохранение данных
        save_data(data)

        await update.message.reply_text(f"Товары {', '.join(names)} успешно добавлены.")
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

# Команда /list — просмотр всех товаров
async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed_chat_id = -1002151355212
    required_topic_id = TOPIC_IDS["products_management"]

    # Проверка чата и темы
    if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != required_topic_id:
        await update.message.reply_text("Эта команда доступна только в теме 'Списания'.")
        return

    data = load_data()
    if not data['products']:
        await update.message.reply_text("Список товаров пуст.")
        return

    # Сортируем товары по дате истечения срока годности
    sorted_products = sorted(data['products'], key=lambda x: datetime.datetime.fromisoformat(x['expiry_date']))

    message = "Список товаров:\n"
    for product in sorted_products:
        expiry_date = datetime.datetime.fromisoformat(product['expiry_date']).strftime("%d.%m.%Y %H:%M")
        message += f"{product['id']}. {product['name']} - срок годности: {expiry_date}\n"

    await update.message.reply_text(message)

# Команда /edit — изменение товара
async def edit_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed_chat_id = -1002151355212
    required_topic_id = TOPIC_IDS["products_management"]

    # Проверка чата и темы
    if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != required_topic_id:
        await update.message.reply_text("Эта команда доступна только в теме 'Списания'.")
        return

    try:
        if len(context.args) < 2:
            await update.message.reply_text("Использование: /edit <ID товара> [новое название] [новая дата и время в формате DD.MM.YYYY HH:MM]")
            return

        product_id = int(context.args[0])
        new_name = None
        new_expiry_date = None

        if len(context.args) > 2:
            # Если больше двух аргументов, объединяем дату и время в один аргумент
            new_name = context.args[1]
            new_expiry_date = " ".join(context.args[2:])
        else:
            # Если только два аргумента, проверяем, что передано: имя или дата
            if "." in context.args[1]:
                new_expiry_date = context.args[1]
            else:
                new_name = context.args[1]

        data = load_data()
        product = next((prod for prod in data['products'] if prod['id'] == product_id), None)

        if not product:
            await update.message.reply_text(f"Товар с ID {product_id} не найден.")
            return

        if new_name:
            product['name'] = new_name

        if new_expiry_date:
            try:
                expiry_time = datetime.datetime.strptime(new_expiry_date, "%d.%m.%Y %H:%M")
                if expiry_time <= datetime.datetime.now():
                    await update.message.reply_text("Ошибка: новая дата и время не могут быть в прошлом.")
                    return
                product['expiry_date'] = expiry_time.isoformat()
            except ValueError:
                await update.message.reply_text("Неверный формат даты. Используйте формат 'DD.MM.YYYY HH:MM'.")
                return

        save_data(data)
        await update.message.reply_text(f"Товар с ID {product_id} успешно обновлен.")

    except ValueError:
        await update.message.reply_text("ID товара должен быть числом.")
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

async def delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed_chat_id = -1002151355212
    required_topic_id = TOPIC_IDS["products_management"]

    # Проверка чата и темы
    if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != required_topic_id:
        await update.message.reply_text("Эта команда доступна только в теме 'Списания'.")
        return

    try:
        # Получение списка ID из аргументов команды
        product_ids = [int(pid.strip()) for pid in context.args]

        data = load_data()
        deleted_ids = []
        not_found_ids = []

        for product_id in product_ids:
            product = next((prod for prod in data['products'] if prod['id'] == product_id), None)
            if product:
                data['products'] = [prod for prod in data['products'] if prod['id'] != product_id]
                deleted_ids.append(product_id)
            else:
                not_found_ids.append(product_id)

        save_data(data)

        # Формирование ответа
        response_messages = []

        if deleted_ids:
            response_messages.append(f"Следующие товары успешно удалены: {', '.join(map(str, deleted_ids))}.")
        if not_found_ids:
            response_messages.append(f"Товары с ID {', '.join(map(str, not_found_ids))} не найдены.")

        await update.message.reply_text("\n".join(response_messages))

    except ValueError:
        await update.message.reply_text("Пожалуйста, укажите корректные ID товаров через пробел.")
    except IndexError:
        await update.message.reply_text("Пожалуйста, укажите хотя бы один ID товара для удаления.")

# Команда /pc — расчет среднего чека
async def calculate_pc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed_chat_id = -1002151355212
    required_topic_id = TOPIC_IDS["pc_and_notifications"]

    # Проверка чата и темы
    if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != required_topic_id:
        await update.message.reply_text("Эта команда доступна только в теме 'Точка контроля'.")
        return

    # Проверка количества аргументов
    if len(context.args) < 1:
        await update.message.reply_text("Использование: /pc: Выручка/Количество чеков")
        return

    expression = context.args[0]
    if "/" not in expression:
        await update.message.reply_text("Неверный формат. Используйте формат: Выручка/Количество чеков.")
        return

    try:
        revenue, checks = map(float, expression.split("/"))
        if checks == 0:
            await update.message.reply_text("Ошибка: количество чеков не может быть равно нулю.")
            return

        average_check = revenue / checks
        current_time = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        message = (f"Точка контроля {current_time}.\n"
                   f"Выручка: {int(revenue)} рублей.\n"
                   f"Чеков: {int(checks)}.\n"
                   f"Средний чек: {int(average_check)} рублей.")
        await update.message.reply_text(message)
    except ValueError:
        await update.message.reply_text("Ошибка: убедитесь, что вы ввели два числа, разделенных '/'.")
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")


# Команда /chat_id - получение chat_id
async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        allowed_chat_id = -1002151355212  # Указанный chat_id, в котором можно использовать команду

        if update.effective_chat.id != allowed_chat_id:
            await update.message.reply_text("Эта команда недоступна в данном чате.")
            return

        await update.message.reply_text(f"Ваш chat_id: {update.effective_chat.id}")
    except Exception as e:
        logger.error(f"Ошибка при получении chat_id: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

async def delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        allowed_chat_id = -1002151355212  # Указанный chat_id, в котором можно использовать команду

        # Проверяем, соответствует ли chat_id допустимому
        if update.effective_chat.id != allowed_chat_id:
            await update.message.reply_text("Эта команда недоступна в данном чате.")
            return

        # Проверяем, цитируется ли сообщение
        if update.message.reply_to_message:
            # Удаляем цитируемое сообщение (сообщение бота)
            await context.bot.delete_message(
                chat_id=update.message.chat_id,
                message_id=update.message.reply_to_message.message_id
            )
            # Удаляем сообщение пользователя (команду /del)
            await context.bot.delete_message(
                chat_id=update.message.chat_id,
                message_id=update.message.message_id
            )
        else:
            # Если сообщение не цитируется
            await update.message.reply_text("Пожалуйста, используйте эту команду, ответив на сообщение бота.")
    except Exception as e:
        # Логируем ошибку и отправляем сообщение об ошибке пользователю
        print(f"Ошибка при удалении сообщений: {e}")
        await update.message.reply_text("Произошла ошибка при попытке удалить сообщение.")

# Функция для отправки уведомления
async def daily_notification(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет уведомление в заданный топик, если уведомления включены."""
    settings = load_settings()
    if not settings.get("notifications_enabled", True):
        return  # Если уведомления отключены, ничего не делаем

    chat_id = -1002151355212  # ID целевого чата
    thread_id = TOPIC_IDS["pc_and_notifications"]  # Тема для уведомлений
    message_text = "Пора сделать точку контроля!"
    current_day = datetime.datetime.now().weekday()  # День недели (0 = Понедельник, 6 = Воскресенье)

    try:
        if current_day != 6:  # Если не воскресенье
            await context.bot.send_message(
                chat_id=chat_id,
                text=message_text,
                message_thread_id=thread_id
            )
            logger.info(f"Уведомление отправлено в чат {chat_id}, топик {thread_id}.")
        else:
            logger.info("Сегодня воскресенье, уведомления не отправляются.")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления: {e}")

def load_help_text():
    """Загружает текст справки из файла."""
    try:
        with open(HELP_TEXT_FILE, 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        return "Не найден документ 'help', обратитесь к разработчику."

# Функция для добавления задач уведомления
def schedule_daily_notifications(job_queue):
    """Планирует ежедневные уведомления в указанные часы, если они включены."""
    settings = load_settings()
    if not settings.get("notifications_enabled", True):
        return  # Если уведомления отключены, не планируем задачи

    notification_times = ["10:00", "12:00", "14:00", "16:00", "18:00"]
    for time in notification_times:
        hours, minutes = map(int, time.split(":"))
        job_queue.run_daily(
            daily_notification,
            time=datetime.time(hour=hours, minute=minutes),
            name=f"Notification at {time}"
        )

# Команда /check_on для включения уведомлений
async def enable_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed_chat_id = -1002151355212
    required_topic_id = TOPIC_IDS["pc_and_notifications"]

    # Проверка чата и темы
    if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != required_topic_id:
        await update.message.reply_text("Эта команда доступна только в теме 'Точка контроля'.")
        return

    try:
        settings = load_settings()
        settings["notifications_enabled"] = True
        save_settings(settings)
        await update.message.reply_text("Уведомления включены.")
        logger.info("Уведомления включены.")
    except Exception as e:
        logger.error(f"Ошибка при включении уведомлений: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

# Команда /check_off для отключения уведомлений
async def disable_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed_chat_id = -1002151355212
    required_topic_id = TOPIC_IDS["pc_and_notifications"]

    # Проверка чата и темы
    if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != required_topic_id:
        await update.message.reply_text("Эта команда доступна только в теме 'Точка контроля'.")
        return

    try:
        settings = load_settings()
        settings["notifications_enabled"] = False
        save_settings(settings)
        await update.message.reply_text("Уведомления отключены.")
        logger.info("Уведомления отключены.")
    except Exception as e:
        logger.error(f"Ошибка при отключении уведомлений: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

# Команда /qr - генерация QR-кода
async def generate_qr_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        allowed_chat_id = -1002151355212

        if update.effective_chat.id != allowed_chat_id:
            await update.message.reply_text("Эта команда недоступна в данном чате.")
            return

        if len(context.args) < 1:
            await update.message.reply_text("Пожалуйста, укажите текст для создания QR-кода.")
            return

        # Получаем текст для генерации QR-кода
        qr_text = " ".join(context.args)

        # Генерация QR-кода
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_text)
        qr.make(fit=True)

        # Сохранение QR-кода в буфер
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        # Отправка QR-кода пользователю
        await update.message.reply_photo(photo=InputFile(buffer, filename="qrcode.png"), caption=f"QR-код для текста: {qr_text}")
    except Exception as e:
        logger.error(f"Ошибка при генерации QR-кода: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

# Команда /topic_id — получение ID темы
async def get_topic_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        allowed_chat_id = -1002151355212  # Указанный chat_id, в котором можно использовать команду

        if update.message.is_topic_message:
            thread_id = update.message.message_thread_id
            await update.message.reply_text(f"ID текущей темы: {thread_id}")
        else:
            await update.message.reply_text("Это сообщение не относится к теме.")
    except Exception as e:
        logger.error(f"Ошибка при получении ID темы: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

# Команда /help — вывод справки по командам
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        allowed_chat_id = -1002151355212  # Указанный chat_id, в котором команда доступна

        # Проверяем, соответствует ли chat_id допустимому
        if update.effective_chat.id != allowed_chat_id:
            await update.message.reply_text("Эта команда недоступна в данном чате.")
            return

        help_text = load_help_text()

        # Убедитесь, что длина текста не превышает 4096 символов
        if len(help_text) > 4096:
            for i in range(0, len(help_text), 4096):
                await update.message.reply_text(help_text[i:i + 4096], parse_mode="Markdown")
        else:
            await update.message.reply_text(help_text, parse_mode="Markdown")
    except Exception as e:
        # Логируем ошибку и отправляем сообщение об ошибке
        print(f"Ошибка при выполнении команды /help: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

async def start_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_time = datetime.datetime.now()

    # Проверяем задержку
    if user_id in last_feedback_time:
        last_time = last_feedback_time[user_id]
        time_diff = (current_time - last_time).total_seconds()
        if time_diff < 300:  # 5 минут = 300 секунд
            await update.message.reply_text("Вы недавно отправляли отзыв. Пожалуйста, подождите 5 минут перед отправкой нового.")
            return ConversationHandler.END

    # Обновляем время последнего сообщения
    last_feedback_time[user_id] = current_time
    await update.message.reply_text("Введите Ваше имя и номер телефона (при необходимости):")
    return ASK_NAME

async def ask_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name_and_contact'] = update.message.text
    await update.message.reply_text("Напишите, что бы Вы хотели улучшить или что Вам не понравилось:\n\nЕсли Вы жалуетесь на блюдо, обязательно укажите что за блюдо, когда оно было приобретено и маркировки на упаковке.")
    return ASK_FEEDBACK

async def ask_response_needed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['feedback'] = update.message.text
    await update.message.reply_text("Хотели ли Вы получить обратную связь? Да/Нет:")
    return ASK_RESPONSE_NEEDED

async def send_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response_needed = update.message.text.strip().lower() in ["да", "yes"]
    context.user_data['response_needed'] = "Да" if response_needed else "Нет"

    feedback_data = (
        f"1. Имя и контакт: {context.user_data['name_and_contact']}\n"
        f"2. Текст: {context.user_data['feedback']}\n"
        f"3. Требуется обратная связь: {context.user_data['response_needed']}\n\n"
        f"Telegram: @{update.message.from_user.username or 'Не указан'}\n"
        f"Время: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )

    chat_id = -1002151355212
    thread_id = TOPIC_IDS["feedback"]
    await context.bot.send_message(chat_id=chat_id, text=feedback_data, message_thread_id=thread_id)

    await update.message.reply_text("Ваш отзыв успешно отправлен! Спасибо за обратную связь.")
    return ConversationHandler.END

async def cancel_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Обратная связь отменена. Если захотите попробовать снова, напишите /fb.")
    return ConversationHandler.END

# Обработчик команды /fb
feedback_handler = ConversationHandler(
    entry_points=[CommandHandler("fb", start_feedback)],
    states={
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_feedback)],
        ASK_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_response_needed)],
        ASK_RESPONSE_NEEDED: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_feedback)],
    },
    fallbacks=[CommandHandler("cancel", cancel_feedback)],
)

# Scheduler commands
async def scheduler_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        allowed_chat_id = -1002151355212
        allowed_topic_id = 4
        if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != allowed_topic_id:
            await update.message.reply_text("Эта команда недоступна в данном чате или теме.")
            return

        args = " ".join(context.args).split()
        if len(args) < 2:
            await update.message.reply_text("Использование: /scheduler_add <позиции через запятую> <приоритет: 1/2/3>")
            return

        *items, priority = args
        items = [item.strip() for item in " ".join(items).split(",") if item.strip()]
        priority = int(priority)
        if priority not in (1, 2, 3):
            await update.message.reply_text("Ошибка: приоритет должен быть 1, 2 или 3.")
            return

        data = load_scheduler_data()
        timestamp = datetime.datetime.now().isoformat()
        added_by = f"@{update.effective_user.username}" if update.effective_user.username else f"User ID: {update.effective_user.id}"

        for item in items:
            data["last_id"] += 1
            task_id = data["last_id"]
            data["tasks"].append({"id": task_id, "name": item, "priority": priority, "date_added": timestamp, "added_by": added_by})

        save_scheduler_data(data)
        await update.message.reply_text(f"Позиции {', '.join(items)} добавлены в очередь {priority}.")
    except Exception as e:
        logger.error(f"Ошибка при добавлении задачи: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

async def scheduler_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        allowed_chat_id = -1002151355212
        allowed_topic_id = 4
        if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != allowed_topic_id:
            await update.message.reply_text("Эта команда недоступна в данном чате или теме.")
            return

        data = load_scheduler_data()
        tasks = data.get("tasks", [])

        if not tasks:
            await update.message.reply_text("Список задач пуст.")
            return

        tasks_by_priority = {1: [], 2: [], 3: []}
        for task in tasks:
            tasks_by_priority[task["priority"]].append(task)

        message = ""
        for priority, tasks in tasks_by_priority.items():
            if tasks:
                message += f"\n\n{priority}-я ОЧЕРЕДЬ:\n"
                for task in sorted(tasks, key=lambda x: x["date_added"]):
                    date_added = datetime.datetime.fromisoformat(task["date_added"]).strftime("%d.%m.%Y %H:%M")
                    added_by = task.get("added_by", f"User ID: {task.get('user_id', 'unknown')}")
                    message += f"{task['id']}. {task['name']} (добавлено {date_added}, {added_by})\n"

        await update.message.reply_text(message or "Список задач пуст.")
    except Exception as e:
        logger.error(f"Ошибка при получении списка задач: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

async def scheduler_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        allowed_chat_id = -1002151355212
        allowed_topic_id = 4
        if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != allowed_topic_id:
            await update.message.reply_text("Эта команда недоступна в данном чате или теме.")
            return

        args = context.args
        if len(args) < 3:
            await update.message.reply_text("Использование: /scheduler_edit <ID задачи> <новое название> <новый приоритет>")
            return

        task_id, new_name, new_priority = int(args[0]), args[1], int(args[2])
        if new_priority not in (1, 2, 3):
            await update.message.reply_text("Ошибка: приоритет должен быть 1, 2 или 3.")
            return

        data = load_scheduler_data()
        task = next((task for task in data["tasks"] if task["id"] == task_id), None)

        if not task:
            await update.message.reply_text(f"Задача с ID {task_id} не найдена.")
            return

        task["name"] = new_name
        task["priority"] = new_priority
        save_scheduler_data(data)

        await update.message.reply_text(f"Позиция \"{new_name}\" с ID {task_id} обновлена.")
    except Exception as e:
        logger.error(f"Ошибка при редактировании задачи: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

async def scheduler_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        allowed_chat_id = -1002151355212
        allowed_topic_id = 4
        if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != allowed_topic_id:
            await update.message.reply_text("Эта команда недоступна в данном чате или теме.")
            return

        args = context.args
        if not args:
            await update.message.reply_text("Использование: /scheduler_delete <ID задачи>[, ID задачи]")
            return

        task_ids = [int(arg.strip()) for arg in " ".join(args).split(",") if arg.strip().isdigit()]
        data = load_scheduler_data()
        logs = load_logs()
        timestamp = datetime.datetime.now().isoformat()

        deleted = []
        for task_id in task_ids:
            task = next((task for task in data["tasks"] if task["id"] == task_id), None)
            if task:
                logs["logs"].append({
                    "date_added": task["date_added"],
                    "name": task["name"],
                    "priority": task["priority"],
                    "date_deleted": timestamp,
                    "deleted_by": update.effective_user.username or "unknown"
                })
                data["tasks"].remove(task)
                deleted.append(task_id)

        save_scheduler_data(data)
        save_logs(logs)

        await update.message.reply_text(f"Удалены задачи с ID: {', '.join(map(str, deleted))}.")
    except Exception as e:
        logger.error(f"Ошибка при удалении задачи: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

async def scheduler_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        allowed_chat_id = -1002151355212
        allowed_topic_id = 4
        if update.effective_chat.id != allowed_chat_id or update.message.message_thread_id != allowed_topic_id:
            await update.message.reply_text("Эта команда недоступна в данном чате или теме.")
            return

        logs = load_logs()["logs"]
        now = datetime.datetime.now()
        two_weeks_ago = now - datetime.timedelta(weeks=2)

        logs = [log for log in logs if datetime.datetime.fromisoformat(log["date_deleted"]) >= two_weeks_ago]

        message = "Логи за последние 2 недели:\n\n"
        for log in logs:
            date_added = datetime.datetime.fromisoformat(log["date_added"]).strftime("%d.%m.%Y %H:%M")
            date_deleted = datetime.datetime.fromisoformat(log["date_deleted"]).strftime("%d.%m.%Y %H:%M")
            message += (
                f"Добавлено: {date_added} | Позиция: {log['name']} | Приоритет: {log['priority']} | "
                f"Удалено: {date_deleted} | Удалил: {log['deleted_by']}\n\n"
            )

        await update.message.reply_text(message or "Логи за последние 2 недели отсутствуют.")
    except Exception as e:
        logger.error(f"Ошибка при получении логов: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")

# Приветствие и автоматическая подписка
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать!\n\n"
        "Я создан, чтобы сделать Вашу жизнь проще. Если у вас есть идеи, предложения или вопросы, используйте команду /fb для обратной связи.\n\n"
        "Мы ценим ваше мнение. Спасибо!"
    )

# Основной запуск бота
async def main():
    global bot
    application = Application.builder().token("7265766358:AAHgiiT_tes-U5GUxvseEhpE0cIU49B_VEw").build()

    # Обработчики команд
    application.add_handler(CommandHandler("add", add_product))
    application.add_handler(CommandHandler("list", list_products))
    application.add_handler(CommandHandler("edit", edit_product))
    application.add_handler(CommandHandler("delete", delete_product))
    application.add_handler(CommandHandler("pc", calculate_pc))
    application.add_handler(CommandHandler("chat_id", get_chat_id))
    application.add_handler(CommandHandler("del", delete_message))
    application.add_handler(CommandHandler("check_on", enable_notifications))
    application.add_handler(CommandHandler("check_off", disable_notifications))
    application.add_handler(CommandHandler("qr", generate_qr_code))
    application.add_handler(CommandHandler("topic_id", get_topic_id))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(feedback_handler)
    application.add_handler(CommandHandler("sc_add", scheduler_add))
    application.add_handler(CommandHandler("sc_list", scheduler_list))
    application.add_handler(CommandHandler("sc_edit", scheduler_edit))
    application.add_handler(CommandHandler("sc_delete", scheduler_delete))
    application.add_handler(CommandHandler("sc_logs", scheduler_logs))
    application.add_handler(CommandHandler("start", send_welcome))

    # Проверка истечения срока годности каждую минуту
    job_queue = application.job_queue
    job_queue.run_repeating(check_expirations, interval=60, first=0)

    # Планирование задач уведомления
    schedule_daily_notifications(job_queue)

    # Использование метода run_polling() вместо start_polling()
    try:
        await application.run_polling()
    finally:
        await application.shutdown()

if __name__ == '__main__':
    import asyncio

    # Запуск основного события с учетом активного цикла
    try:
        asyncio.run(main())
    except RuntimeError as e:
        print(f"Ошибка выполнения: {e}")
