import os
import sys
import time
import threading
import uuid
import json
import base64
import concurrent.futures
from collections import OrderedDict
from datetime import datetime, timezone

import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

TOKEN = os.environ.get("TOKEN")
CHANNEL = os.environ.get("CHANNEL")
ADMIN_STR = os.environ.get("ADMIN")
ADMIN = int(ADMIN_STR) if ADMIN_STR else 0
CHANNEL_LINK = "t.me/AnonGroupChat_channel"

if not TOKEN:
    print("ERROR: set TOKEN env var")
    sys.exit(1)

bot = telebot.TeleBot(TOKEN, parse_mode=None)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "data")
SESSION_FILE = os.path.join(DB_DIR, "session.json")
LOG_FILE = os.path.join(DB_DIR, "users.log")
OLD_USERS_JSON = os.path.join(DB_DIR, "users.json")
OLD_ALL_JSON = os.path.join(DB_DIR, "all_users.json")

joined_users = set()
user_langs = {}

db_lock = threading.RLock()

user_messages = {}
msg_relations = OrderedDict()
threads = OrderedDict()
msg_to_thread = OrderedDict()

msg_counter = {}
SPAM_LIMIT = 20
SPAM_WINDOW = 60.0

MAX_TEXT = 4096
MAX_CAPTION = 1024
BOT_ID = None

executor = concurrent.futures.ThreadPoolExecutor(max_workers=20)

media_locks = {}
last_media_time = {}
media_lock_guard = threading.Lock()

stats_msg_id = None
last_stats_count = -1
last_stats_date = None

TEXTS = {
    'ru': {
        'start': "<b>Анонимный чат</b>\n\nСтатус: <b>{status}</b>\n\n/join — зайти в чат\n/exit — выйти из чата\n/rules — правила\n/help — помощь\n/lang — сменить язык",
        'help': "<b>Помощь</b>\n\nВсе сообщения анонимны. Твой ник никто не узнает.\nОтвечай на сообщения (реплаи работают).\nСсылка на канал: {link}\n\n/online — кто в сети\n/check — проверить сообщение",
        'rules': "<b>Правила</b>\n\nПравил нет, отправляйте что хотите.\nНо желательно не засорять чат спамом.\nВам за это ничего не будет, но желательно не засорять...",
        'status_on': "В сети",
        'status_off': "Не в сети",
        'err_not_joined': "<b>Ошибка.</b>\nТы не в чате. Напиши /join.",
        'err_spam': "<b>Ошибка.</b>\nСлишком много сообщений. Подожди минуту.",
        'join_already': "<b>Ты уже в чате.</b>\nСейчас тут: {count}",
        'join_success': "<b>Ты зашел в чат.</b>\nСейчас тут: {count}",
        'exit_already': "<b>Ты и так не в чате.</b>\nСейчас тут: {count}",
        'exit_success': "<b>Ты вышел из чата.</b>\nСейчас тут: {count}",
        'notify_join': "<b>[бот]</b>\nКто-то зашел в чат. Сейчас тут: {count}",
        'notify_exit': "<b>[бот]</b>\nКто-то вышел из чата. Сейчас тут: {count}",
        'restarted': "<b>[бот]</b>\nБот перезапущен. Ты остаешься в чате.",
        'lang_select': "Выбери язык / Select language:",
        'lang_set': "<b>Язык изменен на русский.</b>",
        'reaction': "<b>[реакция]</b>\n+ {emoji}",
        'online': "<b>[бот]</b>\nСейчас в сети: {count}",
        'check_user': "<b>[бот]</b>\nЭто сообщение пользователя.",
        'check_sys': "<b>[бот]</b>\nЭто системное сообщение бота.",
        'stats': "Пользователей в сессии: {count}\nБот: @{botname}\n(Сообщение обновляется автоматически)\n\nUsers in session: {count}\nBot: @{botname}\n(Message updates automatically)",
        'forwarded': "[переслано]",
        'edited': "[изменено]",
        'announcement': "[объявление]"
    },
    'en': {
        'start': "<b>Anonymous Chat</b>\n\nStatus: <b>{status}</b>\n\n/join — join chat\n/exit — leave chat\n/rules — rules\n/help — help\n/lang — change language",
        'help': "<b>Help</b>\n\nAll messages are anonymous. Nobody will know your nickname.\nReply to messages (replies work).\nChannel link: {link}\n\n/online — who is online\n/check — check message",
        'rules': "<b>Rules</b>\n\nNo rules, send whatever you want.\nBut preferably don't flood the chat with spam.\nYou won't get in trouble, but preferably don't flood...",
        'status_on': "Online",
        'status_off': "Offline",
        'err_not_joined': "<b>Error.</b>\nYou are not in the chat. Use /join.",
        'err_spam': "<b>Error.</b>\nToo many messages. Wait a minute.",
        'join_already': "<b>You are already in the chat.</b>\nCurrently online: {count}",
        'join_success': "<b>You joined the chat.</b>\nCurrently online: {count}",
        'exit_already': "<b>You are not in the chat.</b>\nCurrently online: {count}",
        'exit_success': "<b>You left the chat.</b>\nCurrently online: {count}",
        'notify_join': "<b>[bot]</b>\nSomeone joined the chat. Currently online: {count}",
        'notify_exit': "<b>[bot]</b>\nSomeone left the chat. Currently online: {count}",
        'restarted': "<b>[bot]</b>\nBot restarted. You are still in the chat.",
        'lang_select': "Выбери язык / Select language:",
        'lang_set': "<b>Language changed to English.</b>",
        'reaction': "<b>[reaction]</b>\n+ {emoji}",
        'online': "<b>[bot]</b>\nCurrently online: {count}",
        'check_user': "<b>[bot]</b>\nThis is a user message.",
        'check_sys': "<b>[bot]</b>\nThis is a system message.",
        'stats': "Пользователей в сессии: {count}\nБот: @{botname}\n(Сообщение обновляется автоматически)\n\nUsers in session: {count}\nBot: @{botname}\n(Message updates automatically)",
        'forwarded': "[forwarded]",
        'edited': "[edited]",
        'announcement': "[announcement]"
    }
}

def t(uid, key, **kwargs):
    lang = user_langs.get(uid, 'ru')
    text = TEXTS[lang].get(key, TEXTS['ru'].get(key, ''))
    if kwargs:
        return text.format(**kwargs)
    return text

def enc_id(uid):
    s = str(uid)
    xor = "".join(chr(ord(c) ^ 42) for c in s)
    return base64.b64encode(xor.encode()).decode()

def dec_id(enc):
    xor = base64.b64decode(enc.encode()).decode()
    return int("".join(chr(ord(c) ^ 42) for c in xor))

def _append_log(uid, lang):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{enc_id(uid)} {lang}\n")
            f.flush()
    except Exception as e:
        print(f"Log append error: {e}", flush=True)

def save_session_db():
    with db_lock:
        os.makedirs(DB_DIR, exist_ok=True)
        tmp = SESSION_FILE + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump({"joined": [enc_id(u) for u in joined_users]}, f)
            os.replace(tmp, SESSION_FILE)
        except Exception as e:
            print(f"Session save error: {e}", flush=True)

def compact_users_log():
    with db_lock:
        os.makedirs(DB_DIR, exist_ok=True)
        tmp = LOG_FILE + ".tmp"
        try:
            with open(tmp, "w") as f:
                for uid, lang in user_langs.items():
                    f.write(f"{enc_id(uid)} {lang}\n")
            os.replace(tmp, LOG_FILE)
        except Exception as e:
            print(f"Compact error: {e}", flush=True)

def load_db():
    os.makedirs(DB_DIR, exist_ok=True)

    if os.path.exists(OLD_USERS_JSON):
        try:
            with open(OLD_USERS_JSON) as f:
                data = json.load(f)
            for e, lang in data.get("users", {}).items():
                user_langs[dec_id(e)] = lang
            for e in data.get("joined", []):
                joined_users.add(dec_id(e))
            save_session_db()
            os.rename(OLD_USERS_JSON, OLD_USERS_JSON + ".bak")
        except Exception as e:
            print(f"Migration (users.json) error: {e}", flush=True)

    if os.path.exists(OLD_ALL_JSON):
        try:
            with open(OLD_ALL_JSON) as f:
                data = json.load(f)
            for e in data.get("ru", []):
                user_langs[dec_id(e)] = 'ru'
            for e in data.get("en", []):
                user_langs[dec_id(e)] = 'en'
            os.rename(OLD_ALL_JSON, OLD_ALL_JSON + ".bak")
        except Exception as e:
            print(f"Migration (all_users.json) error: {e}", flush=True)

    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) != 2:
                        continue
                    enc, lang = parts
                    try:
                        uid = dec_id(enc)
                    except Exception:
                        continue
                    if lang == '-':
                        user_langs.pop(uid, None)
                        joined_users.discard(uid)
                    elif lang in ('ru', 'en'):
                        user_langs[uid] = lang
        except Exception as e:
            print(f"Log load error: {e}", flush=True)

    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE) as f:
                data = json.load(f)
            for e in data.get("joined", []):
                uid = dec_id(e)
                joined_users.add(uid)
                if uid not in user_langs:
                    user_langs[uid] = 'ru'
        except Exception as e:
            print(f"Session load error: {e}", flush=True)

    compact_users_log()
    save_session_db()

def add_all_user(uid, lang=None):
    with db_lock:
        if uid in user_langs:
            return
        new_lang = lang or 'ru'
        user_langs[uid] = new_lang
        _append_log(uid, new_lang)

def set_user_lang(uid, lang):
    with db_lock:
        if user_langs.get(uid) == lang:
            return
        user_langs[uid] = lang
        _append_log(uid, lang)

def remove_dead_user(uid):
    with db_lock:
        if uid not in user_langs:
            return
        joined_users.discard(uid)
        del user_langs[uid]
        _append_log(uid, '-')
        save_session_db()

def utf16_len(s):
    return len(s.encode("utf-16-le")) // 2

def is_spamming(uid):
    now = time.time()
    times = [x for x in msg_counter.get(uid, []) if now - x < SPAM_WINDOW]
    times.append(now)
    msg_counter[uid] = times
    return len(times) > SPAM_LIMIT

def add_to_od(od, key, val, maxsize):
    od[key] = val
    while len(od) > maxsize:
        od.popitem(last=False)

def get_user_lock(uid):
    with media_lock_guard:
        if uid not in media_locks:
            media_locks[uid] = threading.Lock()
        return media_locks[uid]

def auto_delete_msg(chat_id, message_id, delay=5.0):
    def _del():
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
    threading.Timer(delay, _del).start()

def is_forwarded(msg):
    if getattr(msg, 'forward_origin', None) is not None: return True
    if getattr(msg, 'forward_from', None) is not None: return True
    if getattr(msg, 'forward_from_chat', None) is not None: return True
    if getattr(msg, 'forward_sender_name', None): return True
    if getattr(msg, 'forward_date', None): return True
    return False

def prepend_forwarded(text, entities, prefix):
    new_text = prefix + "\n" + (text or '')
    shift = utf16_len(prefix + "\n")
    if not entities:
        return new_text, None
    new_ents = []
    for e in entities:
        ne = types.MessageEntity(type=e.type, offset=e.offset + shift, length=e.length)
        if getattr(e, 'url', None): ne.url = e.url
        if getattr(e, 'user', None): ne.user = e.user
        if getattr(e, 'language', None): ne.language = e.language
        if getattr(e, 'custom_emoji_id', None): ne.custom_emoji_id = e.custom_emoji_id
        new_ents.append(ne)
    return new_text, new_ents

def fit_text_with_forward(text, entities, max_len, prefix):
    if not text:
        return prefix, None
    if utf16_len(text) + utf16_len(prefix) + 1 <= max_len:
        return prepend_forwarded(text, entities, prefix)
    avail = max_len - utf16_len(prefix) - 1
    while text and utf16_len(text) > avail:
        text = text[:-1]
    if entities:
        lim = utf16_len(text)
        entities = [e for e in entities if e.offset + e.length <= lim]
    return prepend_forwarded(text, entities, prefix)

def send_text_safe(uid, text, entities=None, reply_to=None, sys_msg=False, auto_del=False, lpo=None):
    try:
        kw = {}
        if lpo: kw['link_preview_options'] = lpo
        if sys_msg:
            m = bot.send_message(uid, text, parse_mode='HTML', reply_to_message_id=reply_to, **kw)
        else:
            m = bot.send_message(uid, text, entities=entities, reply_to_message_id=reply_to, **kw)
        if auto_del and m:
            auto_delete_msg(uid, m.message_id)
        return m
    except ApiTelegramException as e:
        if e.error_code == 403:
            remove_dead_user(uid)
        return None
    except Exception:
        return None

def send_media_task(uid, ct, msg, reply_to, fwd=False):
    lock = get_user_lock(uid)
    with lock:
        now = time.time()
        last = last_media_time.get(uid, 0)
        if now - last < 0.3:
            time.sleep(0.3 - (now - last))
        m = None
        try:
            caption = msg.caption or ''
            cap_ent = msg.caption_entities
            if fwd:
                prefix = t(uid, 'forwarded')
                caption, cap_ent = fit_text_with_forward(caption, cap_ent, MAX_CAPTION, prefix)
            else:
                if utf16_len(caption) > MAX_CAPTION:
                    caption = caption[:MAX_CAPTION]
                    cap_ent = None
            if ct == 'photo':
                m = bot.send_photo(uid, msg.photo[-1].file_id, caption=caption, caption_entities=cap_ent, reply_to_message_id=reply_to)
            elif ct == 'video':
                m = bot.send_video(uid, msg.video.file_id, caption=caption, caption_entities=cap_ent, reply_to_message_id=reply_to)
            elif ct == 'document':
                m = bot.send_document(uid, msg.document.file_id, caption=caption, caption_entities=cap_ent, reply_to_message_id=reply_to)
            elif ct == 'audio':
                m = bot.send_audio(uid, msg.audio.file_id, caption=caption, caption_entities=cap_ent, reply_to_message_id=reply_to)
        except ApiTelegramException as e:
            if e.error_code == 403:
                remove_dead_user(uid)
        except Exception:
            pass
        last_media_time[uid] = time.time()
        return m

def send_task_wrapper(uid, ct, msg, reply_to):
    fwd = is_forwarded(msg)
    if ct == 'text':
        text = msg.text or ''
        ents = msg.entities
        if fwd:
            prefix = t(uid, 'forwarded')
            text, ents = fit_text_with_forward(text, ents, MAX_TEXT, prefix)
        lpo = getattr(msg, 'link_preview_options', None)
        return send_text_safe(uid, text, entities=ents, reply_to=reply_to, lpo=lpo)
    elif ct in {'photo', 'video', 'document', 'audio'}:
        return send_media_task(uid, ct, msg, reply_to, fwd=fwd)
    elif ct in {'sticker', 'animation', 'voice', 'video_note'}:
        try:
            if fwd:
                prefix = t(uid, 'forwarded')
                if reply_to:
                    m_hdr = send_text_safe(uid, prefix, reply_to=reply_to)
                    if m_hdr: reply_to = m_hdr.message_id
                else:
                    m_hdr = send_text_safe(uid, prefix)
                    if m_hdr: reply_to = m_hdr.message_id
            if ct == 'sticker':
                return bot.send_sticker(uid, msg.sticker.file_id, reply_to_message_id=reply_to)
            elif ct == 'animation':
                return bot.send_animation(uid, msg.animation.file_id, reply_to_message_id=reply_to)
            elif ct == 'voice':
                return bot.send_voice(uid, msg.voice.file_id, reply_to_message_id=reply_to)
            elif ct == 'video_note':
                return bot.send_video_note(uid, msg.video_note.file_id, reply_to_message_id=reply_to)
        except ApiTelegramException as e:
            if e.error_code == 403:
                remove_dead_user(uid)
            return None
        except Exception:
            return None

def broadcast_message(message, sender_id, parent_thread_id=None):
    try:
        new_thread_id = uuid.uuid4().hex
        new_msg_ids = {}
        sent_relations = []
        targets = [u for u in joined_users if u != sender_id]
        if not targets: return
        ct = message.content_type
        futures = []
        for uid in targets:
            reply_to_id = None
            if parent_thread_id and parent_thread_id in threads:
                p_thread = threads[parent_thread_id]
                if uid == p_thread["author_id"]:
                    reply_to_id = p_thread["original_msg_id"]
                else:
                    reply_to_id = p_thread["msg_ids"].get(uid)
            fut = executor.submit(send_task_wrapper, uid, ct, message, reply_to_id)
            futures.append((uid, fut))
        for uid, fut in futures:
            try:
                m = fut.result(timeout=15)
                if m:
                    new_msg_ids[uid] = m.message_id
                    sent_relations.append((uid, m.message_id))
                    add_to_od(msg_relations, (uid, m.message_id), (sender_id, message.message_id), 50000)
                    add_to_od(msg_to_thread, (uid, m.message_id), new_thread_id, 50000)
            except Exception:
                pass
        user_messages[(sender_id, message.message_id)] = sent_relations
        
        threads[new_thread_id] = {
            "author_id": sender_id,
            "original_msg_id": message.message_id,
            "msg_ids": new_msg_ids
        }
        
        while len(threads) > 50000:
            threads.popitem(last=False)
    except Exception:
        pass

def notify_others(sender_id, text_ru, text_en):
    for u in list(joined_users):
        if u != sender_id:
            txt = text_ru if user_langs.get(u, 'ru') == 'ru' else text_en
            executor.submit(send_text_safe, u, txt, sys_msg=True, auto_del=True)

@bot.message_handler(commands=['say'])
def cmd_say(message):
    uid = message.from_user.id
    if uid != ADMIN: return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return
    offset = len(parts[0]) + 1
    orig_text = parts[1]
    ents = []
    if message.entities:
        for e in message.entities:
            if e.offset >= offset:
                ne = types.MessageEntity(type=e.type, offset=e.offset - offset, length=e.length)
                if getattr(e, 'url', None): ne.url = e.url
                if getattr(e, 'user', None): ne.user = e.user
                if getattr(e, 'language', None): ne.language = e.language
                if getattr(e, 'custom_emoji_id', None): ne.custom_emoji_id = e.custom_emoji_id
                ents.append(ne)

    with db_lock:
        targets = [u for u in user_langs.keys() if u != uid]

    def _send(target_uid):
        pfx = t(target_uid, 'announcement') + "\n"
        shift = utf16_len(pfx)
        new_ents = [types.MessageEntity(type='bold', offset=0, length=shift - 1)]
        for e in ents:
            ne = types.MessageEntity(type=e.type, offset=e.offset + shift, length=e.length)
            if getattr(e, 'url', None): ne.url = e.url
            if getattr(e, 'user', None): ne.user = e.user
            if getattr(e, 'language', None): ne.language = e.language
            if getattr(e, 'custom_emoji_id', None): ne.custom_emoji_id = e.custom_emoji_id
            new_ents.append(ne)
        send_text_safe(target_uid, pfx + orig_text, entities=new_ents, sys_msg=False)

    for u in targets:
        executor.submit(_send, u)

    bot.send_message(uid, f"Разослано: {len(targets)}")

@bot.message_handler(commands=['lang'])
def cmd_lang(message):
    uid = message.from_user.id
    add_all_user(uid)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"), types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"))
    bot.send_message(uid, t(uid, 'lang_select'), reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
def callback_lang(call):
    uid = call.from_user.id
    lang = call.data.split('_')[1]
    set_user_lang(uid, lang)
    bot.edit_message_text(chat_id=uid, message_id=call.message.message_id, text=t(uid, 'lang_set'), parse_mode='HTML')

@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.from_user.id
    add_all_user(uid)
    status = t(uid, 'status_on') if uid in joined_users else t(uid, 'status_off')
    bot.send_message(uid, t(uid, 'start', status=status), parse_mode='HTML')

@bot.message_handler(commands=['help'])
def cmd_help(message):
    uid = message.from_user.id
    add_all_user(uid)
    bot.send_message(uid, t(uid, 'help', link=CHANNEL_LINK), parse_mode='HTML')

@bot.message_handler(commands=['rules'])
def cmd_rules(message):
    uid = message.from_user.id
    add_all_user(uid)
    bot.send_message(uid, t(uid, 'rules'), parse_mode='HTML')

@bot.message_handler(commands=['join'])
def cmd_join(message):
    uid = message.from_user.id
    add_all_user(uid)
    with db_lock:
        already = uid in joined_users
        if not already:
            joined_users.add(uid)
    if already:
        bot.send_message(uid, t(uid, 'join_already', count=len(joined_users)), parse_mode='HTML')
    else:
        save_session_db()
        bot.send_message(uid, t(uid, 'join_success', count=len(joined_users)), parse_mode='HTML')
        notify_others(uid, t(uid, 'notify_join', count=len(joined_users)), t(uid, 'notify_join', count=len(joined_users)))

@bot.message_handler(commands=['exit'])
def cmd_exit(message):
    uid = message.from_user.id
    add_all_user(uid)
    with db_lock:
        in_session = uid in joined_users
        if in_session:
            joined_users.discard(uid)
    if not in_session:
        bot.send_message(uid, t(uid, 'exit_already', count=len(joined_users)), parse_mode='HTML')
    else:
        save_session_db()
        bot.send_message(uid, t(uid, 'exit_success', count=len(joined_users)), parse_mode='HTML')
        notify_others(uid, t(uid, 'notify_exit', count=len(joined_users)), t(uid, 'notify_exit', count=len(joined_users)))

@bot.message_handler(commands=['online'])
def cmd_online(message):
    uid = message.from_user.id
    if uid not in joined_users: return
    msg = bot.send_message(uid, t(uid, 'online', count=len(joined_users)), parse_mode='HTML')
    auto_delete_msg(uid, msg.message_id)

@bot.message_handler(commands=['check'])
def cmd_check(message):
    uid = message.from_user.id
    if uid not in joined_users: return
    if not message.reply_to_message:
        bot.send_message(uid, t(uid, 'check_sys'), parse_mode='HTML')
        return
    target = message.reply_to_message.message_id
    if (uid, target) in msg_relations:
        bot.send_message(uid, t(uid, 'check_user'), parse_mode='HTML')
    else:
        bot.send_message(uid, t(uid, 'check_sys'), parse_mode='HTML')

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'sticker', 'animation', 'voice', 'video_note'])
def handle_any(message):
    if message.chat.type != 'private': return
    if message.text and message.text.startswith('/'): return
    uid = message.from_user.id
    add_all_user(uid)
    if uid not in joined_users:
        bot.send_message(uid, t(uid, 'err_not_joined'), parse_mode='HTML')
        return
    if is_spamming(uid):
        bot.send_message(uid, t(uid, 'err_spam'), parse_mode='HTML')
        return
    parent_thread_id = None
    if message.reply_to_message:
        parent_thread_id = msg_to_thread.get((uid, message.reply_to_message.message_id))
    threading.Thread(target=broadcast_message, args=(message, uid, parent_thread_id), daemon=True).start()

@bot.edited_message_handler(content_types=['text', 'photo', 'video', 'document', 'audio'])
def handle_edit(message):
    if message.chat.type != 'private': return
    uid = message.from_user.id
    if uid not in joined_users: return
    key = (uid, message.message_id)
    if key not in user_messages: return
    relations = user_messages[key]
    fwd = is_forwarded(message)
    fwd_prefix = t(uid, 'forwarded')

    if message.content_type == 'text':
        orig_text = message.text or ''
        ents = list(message.entities or [])
        if fwd:
            orig_text, ents = prepend_forwarded(orig_text, ents, fwd_prefix)
            ents = list(ents) if ents else []
        if len(orig_text) + 15 > MAX_TEXT:
            orig_text = orig_text[:MAX_TEXT - 15]
            if ents:
                lim = utf16_len(orig_text)
                ents = [e for e in ents if e.offset + e.length <= lim]
        for r_id, b_id in relations:
            edit_word = t(r_id, 'edited')
            edit_sfx = "\n\n" + edit_word
            new_text = orig_text + edit_sfx
            offset = utf16_len(orig_text) + 2
            e_copy = list(ents)
            e_copy.append(types.MessageEntity(type='bold', offset=offset, length=utf16_len(edit_word)))
            def edit_task(target_uid=r_id, msg_id=b_id, txt=new_text, e=e_copy):
                try: bot.edit_message_text(txt, chat_id=target_uid, message_id=msg_id, entities=e)
                except ApiTelegramException as err:
                    if err.error_code == 403: remove_dead_user(target_uid)
                except Exception: pass
            executor.submit(edit_task)
    else:
        orig_cap = message.caption or ''
        ents = list(message.caption_entities or [])
        if fwd:
            orig_cap, ents = prepend_forwarded(orig_cap, ents, fwd_prefix)
            ents = list(ents) if ents else []
        if len(orig_cap) + 15 > MAX_CAPTION:
            orig_cap = orig_cap[:MAX_CAPTION - 15]
            if ents:
                lim = utf16_len(orig_cap)
                ents = [e for e in ents if e.offset + e.length <= lim]
        for r_id, b_id in relations:
            edit_word = t(r_id, 'edited')
            edit_sfx = "\n\n" + edit_word
            new_cap = orig_cap + edit_sfx
            offset = utf16_len(orig_cap) + 2
            e_copy = list(ents)
            e_copy.append(types.MessageEntity(type='bold', offset=offset, length=utf16_len(edit_word)))
            def edit_media(target_uid=r_id, msg_id=b_id, cap=new_cap, e=e_copy):
                try: bot.edit_message_caption(chat_id=target_uid, message_id=msg_id, caption=cap, caption_entities=e)
                except ApiTelegramException as err:
                    if err.error_code == 403: remove_dead_user(target_uid)
                except Exception: pass
            executor.submit(edit_media)

@bot.message_reaction_handler()
def handle_reaction(reaction):
    if not reaction.user: return
    uid = reaction.user.id
    if uid not in joined_users: return
    key = (uid, reaction.message_id)
    if key not in msg_relations: return
    author_id, orig_msg_id = msg_relations[key]
    old_emojis = {r.emoji for r in reaction.old_reaction if getattr(r, 'type', '') == 'emoji'}
    new_emojis = {r.emoji for r in reaction.new_reaction if getattr(r, 'type', '') == 'emoji'}
    added = new_emojis - old_emojis
    if not added: return
    emoji = list(added)[0]
    if author_id != uid:
        executor.submit(send_text_safe, author_id, t(author_id, 'reaction', emoji=emoji), reply_to=orig_msg_id, sys_msg=True)
    relations = user_messages.get((author_id, orig_msg_id), [])
    for r_id, b_id in relations:
        if r_id != uid:
            executor.submit(send_text_safe, r_id, t(r_id, 'reaction', emoji=emoji), reply_to=b_id, sys_msg=True)

def channel_stats_loop(bot_username):
    global stats_msg_id, last_stats_count, last_stats_date
    if not CHANNEL: return
    try:
        channel_id = int(CHANNEL) if str(CHANNEL).startswith('-100') else CHANNEL
    except ValueError:
        channel_id = CHANNEL
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            current_date = now_utc.date()
            count = len(joined_users)
            recreate = False
            if last_stats_date != current_date:
                recreate = True
                last_stats_date = current_date
            elif count != last_stats_count:
                recreate = False
            if recreate or count != last_stats_count:
                text = t('ru', 'stats').format(count=count, botname=bot_username)
                if recreate and stats_msg_id:
                    try: bot.delete_message(channel_id, stats_msg_id)
                    except Exception: pass
                    stats_msg_id = None
                if not stats_msg_id:
                    msg = bot.send_message(channel_id, text, parse_mode='HTML')
                    stats_msg_id = msg.message_id
                else:
                    try:
                        bot.edit_message_text(text, chat_id=channel_id, message_id=stats_msg_id, parse_mode='HTML')
                    except Exception:
                        msg = bot.send_message(channel_id, text, parse_mode='HTML')
                        stats_msg_id = msg.message_id
                last_stats_count = count
        except Exception:
            pass
        time.sleep(60)

def compact_loop():
    while True:
        time.sleep(3600)
        try:
            compact_users_log()
        except Exception:
            pass

if __name__ == "__main__":
    load_db()
    bot.remove_webhook()
    me = bot.get_me()
    BOT_ID = me.id
    commands_ru = [
        types.BotCommand("start", "Начать"),
        types.BotCommand("join", "Зайти в чат"),
        types.BotCommand("exit", "Выйти из чата"),
        types.BotCommand("rules", "Правила"),
        types.BotCommand("help", "Помощь"),
        types.BotCommand("lang", "Сменить язык"),
        types.BotCommand("online", "Кто в сети"),
        types.BotCommand("check", "Проверить сообщение")
    ]
    commands_en = [
        types.BotCommand("start", "Start"),
        types.BotCommand("join", "Join chat"),
        types.BotCommand("exit", "Leave chat"),
        types.BotCommand("rules", "Rules"),
        types.BotCommand("help", "Help"),
        types.BotCommand("lang", "Change language"),
        types.BotCommand("online", "Who is online"),
        types.BotCommand("check", "Check message")
    ]
    try:
        bot.set_my_commands(commands_ru, language_code='ru')
        bot.set_my_commands(commands_en, language_code='en')
        bot.set_my_commands(commands_en)
    except Exception:
        pass

    def restart_notify():
        for u in list(joined_users):
            try:
                bot.send_message(u, t(u, 'restarted'), parse_mode='HTML')
                time.sleep(0.05)
            except ApiTelegramException as e:
                if e.error_code == 403: remove_dead_user(u)
            except Exception: pass
    threading.Thread(target=restart_notify, daemon=True).start()
    threading.Thread(target=channel_stats_loop, args=(me.username,), daemon=True).start()
    threading.Thread(target=compact_loop, daemon=True).start()
    print("[start] Bot is running", flush=True)
    bot.infinity_polling(timeout=30, long_polling_timeout=25, allowed_updates=['message', 'edited_message', 'message_reaction', 'callback_query'])
