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
    
    keyboard = []
    if buttons:
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
            schedule.every
