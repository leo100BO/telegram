import telegram
from telegram.ext import (Updater, CommandHandler, ConversationHandler, MessageHandler, Filters)
import schedule
import time
import json
import threading
import uuid
from datetime import datetime, time as dt_time
import os
import pytz

# --- НАЛАШТУВАННЯ ---
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID'))
REMINDERS_FILE = 'reminders.json'
KYIV_TZ = pytz.timezone("Europe/Kyiv")
WEEKDAYS_MAP = {0: 'пн', 1: 'вт', 2: 'ср', 3: 'чт', 4: 'пт', 5: 'сб', 6: 'нд'}

# Визначаємо стани для діалогів
ADD_GET_MEDIA, ADD_GET_DETAILS = range(2)
NOW_GET_MEDIA, NOW_GET_DETAILS = range(2, 4)

# --- РОБОТА З ФАЙЛОМ НАГАДУВАНЬ ---
def load_reminders():
    try:
        with open(REMINDERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        with open(REMINDERS_FILE, 'w') as f:
            json.dump([], f)
        return []

def save_reminders(reminders):
    with open(REMINDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(reminders, f, indent=4, ensure_ascii=False)

# --- ОСНОВНІ ФУНКЦІЇ БОТА ---
def send_reminder(bot, reminder):
    # --- ОНОВЛЕНО: Додано parse_mode='HTML' ---
    if reminder.get('excluded_days'):
        current_weekday_kyiv = WEEKDAYS_MAP[datetime.now(KYIV_TZ).weekday()]
        if current_weekday_kyiv in reminder['excluded_days']:
            print(f"[{datetime.now(KYIV_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Пропущено ID {reminder['id']} (виключений день: {current_weekday_kyiv}).")
            return

    chat_id = int(reminder['chat_id'])
    text = reminder['text']
    media_file_id = reminder.get('media_file_id')
    media_type = reminder.get('media_type')

    try:
        if media_file_id:
            if media_type == 'photo':
                bot.send_photo(chat_id=chat_id, photo=media_file_id, caption=text, parse_mode='HTML')
            elif media_type == 'animation':
                bot.send_animation(chat_id=chat_id, animation=media_file_id, caption=text, parse_mode='HTML')
            elif media_type == 'video':
                bot.send_video(chat_id=chat_id, video=media_file_id, caption=text, parse_mode='HTML')
        else:
            bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
        print(f"[{datetime.now(KYIV_TZ).strftime('%Y-%m-%d %H:%M:%S')}] ✅ Повідомлення ID {reminder['id']} успішно надіслано в чат {chat_id}")
    except Exception as e:
        print(f"[{datetime.now(KYIV_TZ).strftime('%Y-%m-%d %H:%M:%S')}] ❌ Помилка відправки ID {reminder['id']} в чат {chat_id}: {e}")

def schedule_reminder(bot, reminder):
    job_func = lambda: send_reminder(bot, reminder)
    parts = reminder['schedule_time'].split()
    day_or_freq, local_time_str = parts
    job_tag = reminder['id']

    try:
        hour, minute = map(int, local_time_str.split(':'))
        now_in_kyiv = datetime.now(KYIV_TZ)
        today_in_kyiv_at_time = now_in_kyiv.replace(hour=hour, minute=minute, second=0, microsecond=0)
        utc_dt = today_in_kyiv_at_time.astimezone(pytz.utc)
        utc_time_str = utc_dt.strftime("%H:%M")

        print(f"Планування ID {reminder['id']}: Київський час '{local_time_str}' -> UTC час для сервера '{utc_time_str}'")

        if day_or_freq.lower() == 'щодня':
            schedule.every().day.at(utc_time_str).do(job_func).tag(job_tag)
        else:
            days_map = {'щопонеділка': schedule.every().monday, 'щовівторка': schedule.every().tuesday, 'щосереди': schedule.every().wednesday, 'щочетверга': schedule.every().thursday, 'щоп\'ятниці': schedule.every().friday, 'щосуботи': schedule.every().saturday, 'щонеділі': schedule.every().sunday}
            days_map[day_or_freq.lower()].at(utc_time_str).do(job_func).tag(job_tag)
        return True
    except Exception as e:
        print(f"Помилка планування ID {reminder.get('id', 'N/A')}: {e}")
        return False

# --- ДІАЛОГИ ТА КОМАНДИ ---
def start_add(update, context):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    update.message.reply_text("Крок 1: Надішліть фото/GIF/відео, або /skip, щоб пропустити.\n\nДля скасування введіть /cancel.")
    return ADD_GET_MEDIA

def get_media_add(update, context):
    media_file = update.message.photo[-1] if update.message.photo else update.message.animation or update.message.video
    context.user_data['media_file_id'] = media_file.file_id
    context.user_data['media_type'] = 'photo' if update.message.photo else 'animation' if update.message.animation else 'video'
    update.message.reply_text("Крок 2: Надішліть деталі: `<id_чату> \"<розклад>\" \"<текст>\" [виключити:дн,дн]`")
    return ADD_GET_DETAILS

def skip_media_add(update, context):
    context.user_data['media_file_id'] = None
    update.message.reply_text("Крок 2: Надішліть деталі: `<id_чату> \"<розклад>\" \"<текст>\" [виключити:дн,дн]`")
    return ADD_GET_DETAILS

def get_details_add(update, context):
    try:
        full_command_str = update.message.text
        excluded_days = []
        if 'виключити:' in full_command_str:
            parts = full_command_str.split(' виключити:')
            full_command_str = parts[0]
            excluded_days = parts[1].strip().split(',')
        chat_id_part, rest_of_string = full_command_str.split(' ', 1)
        chat_id = chat_id_part.strip()
        parts = rest_of_string.split('"')
        schedule_time = parts[1]
        text = parts[3]
        new_reminder = {'id': str(uuid.uuid4())[:8], 'chat_id': chat_id, 'schedule_time': schedule_time, 'text': text, 'excluded_days': excluded_days, 'media_file_id': context.user_data.get('media_file_id'), 'media_type': context.user_data.get('media_type')}
        if not schedule_reminder(context.bot, new_reminder): raise ValueError("Неправильний формат часу/розкладу.")
    except Exception as e:
        update.message.reply_text(f"❌ Помилка: {e}\nСпробуйте знову або /cancel.")
        return ADD_GET_DETAILS
    reminders = load_reminders()
    reminders.append(new_reminder)
    save_reminders(reminders)
    update.message.reply_text(f"✅ Нагадування ID `{new_reminder['id']}` створено.")
    context.user_data.clear()
    return ConversationHandler.END

def start_now(update, context):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    update.message.reply_text("Крок 1: Надішліть фото/GIF/відео для миттєвої відправки, або /skip.\n\nДля скасування введіть /cancel.")
    return NOW_GET_MEDIA

def get_media_now(update, context):
    media_file = update.message.photo[-1] if update.message.photo else update.message.animation or update.message.video
    context.user_data['media_file_id'] = media_file.file_id
    context.user_data['media_type'] = 'photo' if update.message.photo else 'animation' if update.message.animation else 'video'
    update.message.reply_text("Крок 2: Надішліть деталі для відправки: `<id_чату> \"<текст>\"`")
    return NOW_GET_DETAILS

def skip_media_now(update, context):
    context.user_data['media_file_id'] = None
    update.message.reply_text("Крок 2: Надішліть деталі для відправки: `<id_чату> \"<текст>\"`")
    return NOW_GET_DETAILS

def get_details_now(update, context):
    try:
        full_command_str = update.message.text
        chat_id_part, rest_of_string = full_command_str.split(' ', 1)
        chat_id = chat_id_part.strip()
        text = rest_of_string.split('"')[1]
        instant_reminder = {'id': 'now', 'chat_id': chat_id, 'text': text, 'media_file_id': context.user_data.get('media_file_id'), 'media_type': context.user_data.get('media_type')}
        send_reminder(context.bot, instant_reminder)
        update.message.reply_text("✅ Повідомлення надіслано.")
    except Exception as e:
        update.message.reply_text(f"❌ Помилка: {e}\nСпробуйте знову або /cancel.")
        return NOW_GET_DETAILS
    context.user_data.clear()
    return ConversationHandler.END

def cancel(update, context):
    update.message.reply_text("Дію скасовано.")
    context.user_data.clear()
    return ConversationHandler.END

def start(update, context):
    user_id = update.effective_user.id
    update.message.reply_text(f"👋 Привіт! Я бот для нагадувань.\nВаш Telegram ID: `{user_id}`")
    if user_id == ADMIN_ID:
        show_help(update, context)

def show_help(update, context):
    """Надсилає довідкове повідомлення."""
    help_text = (
        "*Довідка по командам:*\n\n"
        "`/add` - Запустити діалог для створення нового нагадування.\n\n"
        "`/now` - Запустити діалог для миттєвої відправки повідомлення.\n\n"
        "`/list` - Показати список усіх активних нагадувань.\n\n"
        "`/delete <ID>` - Видалити нагадування. Наприклад: `/delete 1a2b3c4d`\n\n"
        "`/cancel` - Скасувати поточну дію (`/add` або `/now`).\n\n"
        "`/help` - Показати цю довідку.\n\n"
        "Для форматування тексту використовуйте HTML-теги:\n"
        "`<b>жирний</b>`, `<i>курсив</i>`, `<u>підкреслений</u>`."
    )
    update.message.reply_text(help_text, parse_mode='Markdown')

def list_reminders(update, context):
    if update.effective_user.id != ADMIN_ID: return
    reminders = load_reminders()
    if not reminders:
        update.message.reply_text("Список нагадувань порожній."); return
    message = "📋 *Активні нагадування:*\n\n"
    for r in reminders:
        message += f"*ID:* `{r['id']}`\n*Чат:* `{r['chat_id']}`\n*Розклад:* `{r['schedule_time']}`\n"
        if r.get('excluded_days'): message += f"*Виключені дні:* {', '.join(r['excluded_days'])}\n"
        message += f"*Текст:* _{r['text']}_\n"
        if r.get('media_file_id'): message += f"*Медіа:* Прикріплено\n"
        message += "--------------------\n"
    update.message.reply_text(message, parse_mode='Markdown')

def delete_reminder(update, context):
    if update.effective_user.id != ADMIN_ID: return
    try: reminder_id_to_delete = context.args[0]
    except IndexError:
        update.message.reply_text("❌ Вкажіть ID нагадування.", parse_mode='Markdown'); return
    reminders = load_reminders()
    new_reminders = [r for r in reminders if r['id'] != reminder_id_to_delete]
    if len(new_reminders) < len(reminders):
        save_reminders(new_reminders); schedule.clear(reminder_id_to_delete)
        update.message.reply_text(f"✅ Нагадування ID `{reminder_id_to_delete}` видалено.")
    else:
        update.message.reply_text(f"🤷‍♂️ Нагадування ID `{reminder_id_to_delete}` не знайдено.")

# --- ЗАПУСК БОТА ---
def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    add_conv = ConversationHandler(entry_points=[CommandHandler('add', start_add)], states={ADD_GET_MEDIA: [MessageHandler(Filters.photo | Filters.video | Filters.animation, get_media_add), CommandHandler('skip', skip_media_add)], ADD_GET_DETAILS: [MessageHandler(Filters.text & ~Filters.command, get_details_add)]}, fallbacks=[CommandHandler('cancel', cancel)])
    now_conv = ConversationHandler(entry_points=[CommandHandler('now', start_now)], states={NOW_GET_MEDIA: [MessageHandler(Filters.photo | Filters.video | Filters.animation, get_media_now), CommandHandler('skip', skip_media_now)], NOW_GET_DETAILS: [MessageHandler(Filters.text & ~Filters.command, get_details_now)]}, fallbacks=[CommandHandler('cancel', cancel)])

    dp.add_handler(add_conv)
    dp.add_handler(now_conv)
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", show_help))
    dp.add_handler(CommandHandler("list", list_reminders))
    dp.add_handler(CommandHandler("delete", delete_reminder))

    print("Завантаження існуючих нагадувань...")
    for r in load_reminders():
        try: schedule_reminder(updater.bot, r)
        except Exception as e: print(f"Помилка при завантаженні існуючого нагадування ID {r.get('id', 'N/A')}: {e}")

    print("Планування завершено.")

    thread = threading.Thread(target=run_scheduler); thread.daemon = True; thread.start()

    print("Бот запущений...")
    updater.start_polling()
    updater.idle()
  
if __name__ == '__main__':
    main()