import telegram
from telegram.ext import (Updater, CommandHandler, ConversationHandler, MessageHandler, Filters, CallbackQueryHandler)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import schedule
import time
import json
import threading
import uuid
from datetime import datetime
import os
import pytz
import re

# --- НАЛАШТУВАННЯ ---
BOT_TOKEN = os.environ.get('BOT_TOKEN')
allowed_ids_str = os.environ.get('ALLOWED_USER_IDS', '')
ALLOWED_USER_IDS = [int(id.strip()) for id in allowed_ids_str.split(',') if id.strip()]

REMINDERS_FILE = 'reminders.json'
KYIV_TZ = pytz.timezone("Europe/Kyiv")
WEEKDAYS_MAP = {0: 'пн', 1: 'вт', 2: 'ср', 3: 'чт', 4: 'пт', 5: 'сб', 6: 'нд'}

ADD_GET_MEDIA, ADD_GET_DETAILS = range(2)
NOW_GET_MEDIA, NOW_GET_DETAILS = range(2, 4)

# --- ФУНКЦІЯ ПЕРЕВІРКИ ДОСТУПУ ---
def is_user_allowed(update):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USER_IDS:
        update.message.reply_text("⛔ Вибачте, у вас немає доступу до цього бота.")
        return False
    return True

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
    if reminder.get('excluded_days'):
        current_weekday_kyiv = WEEKDAYS_MAP[datetime.now(KYIV_TZ).weekday()]
        if current_weekday_kyiv in reminder['excluded_days']:
            print(f"[{datetime.now(KYIV_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Пропущено ID {reminder['id']} (виключений день: {current_weekday_kyiv}).")
            return
    
    chat_ids = reminder.get('chat_ids', [])
    text = reminder['text']
    media_file_id = reminder.get('media_file_id')
    media_type = reminder.get('media_type')
    buttons = reminder.get('buttons')
    
    # --- ОНОВЛЕНО: Створюємо горизонтальну клавіатуру ---
    keyboard = []
    if buttons:
        # Всі кнопки додаються в один внутрішній список, щоб вони були в одному рядку
        keyboard = [[
            InlineKeyboardButton(btn_text, callback_data=f"btn_press:{reminder['id']}:{i}")
            for i, btn_text in enumerate(buttons)
        ]]
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    clean_text = re.sub(r'\[\[.*?\]\]', '', text).strip()

    for chat_id in chat_ids:
        try:
            target_chat_id = int(chat_id)
            if media_file_id:
                if media_type == 'photo':
                    bot.send_photo(chat_id=target_chat_id, photo=media_file_id, caption=clean_text, parse_mode='HTML', reply_markup=reply_markup)
                elif media_type == 'animation':
                    bot.send_animation(chat_id=target_chat_id, animation=media_file_id, caption=clean_text, parse_mode='HTML', reply_markup=reply_markup)
                elif media_type == 'video':
                    bot.send_video(chat_id=target_chat_id, video=media_file_id, caption=clean_text, parse_mode='HTML', reply_markup=reply_markup)
            else:
                bot.send_message(chat_id=target_chat_id, text=clean_text, parse_mode='HTML', reply_markup=reply_markup)
            print(f"[{datetime.now(KYIV_TZ).strftime('%Y-%m-%d %H:%M:%S')}] ✅ Повідомлення ID {reminder.get('id', 'N/A')} успішно надіслано в чат {chat_id}")
            time.sleep(0.1)
        except Exception as e:
            print(f"[{datetime.now(KYIV_TZ).strftime('%Y-%m-%d %H:%M:%S')}] ❌ Помилка відправки ID {reminder.get('id', 'N/A')} в чат {chat_id}: {e}")

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
        print(f"Планування ID {reminder['id']}: '{reminder['schedule_time']}' -> UTC час '{utc_time_str}'")
        if day_or_freq.lower() == 'щодня':
            schedule.every().day.at(utc_time_str).do(job_func).tag(job_tag)
        else:
            days_map = {'щопонеділка': schedule.every().monday, 'щовівторка': schedule.every().tuesday, 'щосереди': schedule.every().wednesday, 'щочетверга': schedule.every().thursday, 'щоп\'ятниці': schedule.every().friday, 'щосуботи': schedule.every().saturday, 'щонеділі': schedule.every().sunday}
            days_map[day_or_freq.lower()].at(utc_time_str).do(job_func).tag(job_tag)
        return True
    except Exception as e:
        print(f"Помилка планування ID {reminder.get('id', 'N/A')}: {e}")
        return False

# --- ОБРОБКА НАТИСКАННЯ КНОПОК ---
def button_callback(update, context):
    query = update.callback_query
    query.answer()
    
    try:
        action, reminder_id, button_index_str = query.data.split(':')
        button_index = int(button_index_str)
        
        reminders = load_reminders()
        target_reminder = next((r for r in reminders if r['id'] == reminder_id), None)
        
        if not target_reminder:
            query.edit_message_text(text=query.message.text_html + "\n\n🤷‍♂️ Не вдалося знайти це нагадування.", parse_mode='HTML')
            return

        button_text = target_reminder['buttons'][button_index]
        time_str = datetime.now(KYIV_TZ).strftime('%H:%M:%S')
        
        original_text = query.message.text_html if query.message.text_html else query.message.caption_html
        
        if f"✅ <b>{button_text}</b>" not in original_text:
            new_text = original_text + f"\n✅ <b>{button_text}</b> виконано о {time_str}"
            # --- ОНОВЛЕНО: Прибираємо кнопки після натискання ---
            query.edit_message_text(text=new_text, parse_mode='HTML', reply_markup=None)
            
    except Exception as e:
        print(f"Помилка обробки кнопки: {e}")

# --- ДІАЛОГИ ТА КОМАНДИ ---
def start_add(update, context):
    if not is_user_allowed(update): return ConversationHandler.END
    update.message.reply_text("Крок 1: Надішліть медіа, або /skip.")
    return ADD_GET_MEDIA

def get_media_add(update, context):
    media_file = update.message.photo[-1] if update.message.photo else update.message.animation or update.message.video
    context.user_data['media_file_id'] = media_file.file_id
    context.user_data['media_type'] = 'photo' if update.message.photo else 'animation' if update.message.animation else 'video'
    update.message.reply_text("Крок 2: Надішліть деталі:\n<id_чату...> \"<розклад>\" \"<текст з кнопками [[...]]>\" виключити:дн,дн")
    return ADD_GET_DETAILS

def skip_media_add(update, context):
    context.user_data['media_file_id'] = None
    update.message.reply_text("Крок 2: Надішліть деталі:\n<id_чату...> \"<розклад>\" \"<текст з кнопками [[...]]>\" виключити:дн,дн")
    return ADD_GET_DETAILS

def get_details_add(update, context):
    try:
        full_command_str = update.message.text
        excluded_days = []
        if ' виключити:' in full_command_str:
            parts = full_command
