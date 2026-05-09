import os
import time
import threading
import datetime
import sqlite3
import requests
from groq import Groq

VK_TOKEN = os.environ.get("vk1.a.RfVgt3N_nMfp3Fb_OUo2_DDJgr3UnDUAe_C5ASkDAmBXQYSJUxsIe14jhOuK6E0TfVnHUVarQYpaSkYUWc57OBo9LBV6ToRMldxGyc5pM3FXIQvkHUHi0d44MGi7oDeHfTa1hMqRrIW1jcBg1Pw7zbQ8omwIL3puIDAiGXmFdRRo9lPjDtfB1feijSuqcYIeiE1kLy-TMHUVri5pNxxaUQ")
GROQ_API_KEY = os.environ.get("gsk_rugzLFI9Y3XQMZPnm4EqWGdyb3FYh5XN39khuUM9HIJarW8vks6cY")
VK_GROUP_ID = os.environ.get("236136575")

VK_API = "https://api.vk.com/method"
VK_VERSION = "5.131"

groq_client = Groq(api_key=GROQ_API_KEY)


# ─── База данных ───────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect("wins.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS wins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                original TEXT NOT NULL,
                reframed TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                registered_at TEXT NOT NULL
            )
        """)
        db.commit()


def register_user(user_id):
    with get_db() as db:
        db.execute(
            "INSERT OR IGNORE INTO users (user_id, registered_at) VALUES (?, ?)",
            (str(user_id), datetime.datetime.now().isoformat())
        )
        db.commit()


def save_win(user_id, original, reframed):
    with get_db() as db:
        db.execute(
            "INSERT INTO wins (user_id, original, reframed, created_at) VALUES (?, ?, ?, ?)",
            (str(user_id), original, reframed, datetime.datetime.now().isoformat())
        )
        db.commit()


def get_wins(user_id, since: datetime.datetime):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM wins WHERE user_id = ? AND created_at >= ? ORDER BY created_at ASC",
            (str(user_id), since.isoformat())
        ).fetchall()
    return rows


def get_all_users():
    with get_db() as db:
        rows = db.execute("SELECT user_id FROM users").fetchall()
    return [r["user_id"] for r in rows]


# ─── VK API ────────────────────────────────────────────────────

def vk(method, **params):
    params["access_token"] = VK_TOKEN
    params["v"] = VK_VERSION
    r = requests.post(f"{VK_API}/{method}", data=params, timeout=10)
    return r.json().get("response")


def send(user_id, text):
    vk("messages.send",
       user_id=user_id,
       message=text,
       random_id=int(time.time() * 1000))


def get_long_poll_server():
    return vk("groups.getLongPollServer", group_id=VK_GROUP_ID)


# ─── ИИ ────────────────────────────────────────────────────────

def ai(system_prompt, user_text, max_tokens=200):
    try:
        resp = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            max_tokens=max_tokens
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq error: {e}")
        return None


def classify_message(text):
    """Определяет тип сообщения: 'win' или 'struggle'"""
    result = ai(
        "Определи тип сообщения пользователя. "
        "Если человек описывает что-то что сделал, пусть даже маленькое — ответь: win. "
        "Если человек выражает усталость, подавленность, говорит что ничего не сделал, "
        "жалуется на день или себя — ответь: struggle. "
        "Отвечай ТОЛЬКО одним словом: win или struggle.",
        text,
        max_tokens=5
    )
    if result and "win" in result.lower():
        return "win"
    return "struggle"


def reframe_win(text):
    """Переформулирует действие как победу"""
    result = ai(
        "Ты тёплый поддерживающий помощник. Человек борется с обесцениванием своих действий. "
        "Возьми любое действие — даже самое маленькое — и переформулируй его как настоящую победу. "
        "Коротко, тепло, без пафоса и без слов 'молодец' и 'браво'. "
        "Максимум 2 предложения на русском. "
        "Примеры: 'выпила воду' → 'Ты позаботилась о себе — это важно.'; "
        "'посмотрела сериал' → 'Ты дала себе отдых. Это тоже нужно.'",
        text
    )
    return result or f"✓ {text}"


def respond_to_struggle(text):
    """Отвечает поддержкой и задаёт один вопрос"""
    result = ai(
        "Ты тёплый поддерживающий помощник. Человек написал что-то тяжёлое — устал, "
        "говорит что ничего не сделал, чувствует себя плохо. "
        "Ответь коротко и тепло — без советов, без оценок, просто поддержи. "
        "Затем задай ОДИН простой вопрос чтобы разговорить — например про утро, "
        "про один момент дня, про что было сложным. "
        "Цель — помочь человеку вспомнить что он всё-таки что-то делал сегодня. "
        "Всё на русском, максимум 4 предложения.",
        text
    )
    return result or "Это бывает, такие дни случаются. Расскажи — как прошло утро?"


def make_daily_summary(wins_list):
    """Формирует вечерний итог с комментарием"""
    wins_text = "\n".join([f"- {w['reframed']}" for w in wins_list])
    comment = ai(
        "Ты тёплый поддерживающий помощник. Перед тобой список маленьких побед человека за день. "
        "Напиши короткий тёплый комментарий — 2-3 предложения — про этот день. "
        "Замечай конкретные детали из списка. Без пафоса, без 'молодец'. "
        "На русском.",
        wins_text,
        max_tokens=150
    )
    lines = [f"🌙 Твой день — {len(wins_list)} {'победа' if len(wins_list) == 1 else 'победы' if len(wins_list) < 5 else 'побед'}:\n"]
    for w in wins_list:
        lines.append(f"• {w['reframed']}")
    if comment:
        lines.append(f"\n{comment}")
    return "\n".join(lines)


def make_period_summary(wins_list, period_name):
    """Формирует отчёт за период"""
    if not wins_list:
        return f"За {period_name} пока нет записей."

    wins_text = "\n".join([f"- {w['reframed']}" for w in wins_list])
    comment = ai(
        "Ты тёплый поддерживающий помощник. Перед тобой список маленьких побед человека за период. "
        "Напиши 3-4 предложения — что ты замечаешь в этом периоде, какие темы повторяются, "
        "что это говорит о человеке. Конкретно и тепло, без пафоса. На русском.",
        wins_text,
        max_tokens=200
    )

    lines = [f"📋 За {period_name} — {len(wins_list)} записей:\n"]
    for w in wins_list:
        dt = datetime.datetime.fromisoformat(w["created_at"])
        lines.append(f"• {dt.strftime('%d.%m')} — {w['reframed']}")
    if comment:
        lines.append(f"\n✨ {comment}")
    return "\n".join(lines)


# ─── Обработка сообщений ───────────────────────────────────────

def handle_message(user_id, text):
    text = text.strip()
    register_user(user_id)

    # Команды
    if text.lower() in ["/старт", "/start", "начать"]:
        send(user_id,
             "Привет 👋\n\n"
             "Я помогу тебе замечать свои маленькие победы и не обесценивать день.\n\n"
             "Просто пиши мне что делаешь или сделала — даже самое маленькое. "
             "Я сохраню это и вечером покажу как прошёл твой день.\n\n"
             "Если напишешь что всё плохо или ничего не сделала — я не буду записывать это как победу, "
             "просто поговорим.\n\n"
             "Команды:\n"
             "/итог — всё за сегодня\n"
             "/неделя — последние 7 дней\n"
             "/месяц — последние 30 дней")
        return

    if text.lower() in ["/итог", "итог"]:
        today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        wins = get_wins(user_id, today)
        if not wins:
            send(user_id, "Сегодня пока нет записей. Напиши что-нибудь — даже 'просто встала' считается ✨")
        else:
            send(user_id, make_daily_summary(wins))
        return

    if text.lower() in ["/неделя", "неделя"]:
        since = datetime.datetime.now() - datetime.timedelta(days=7)
        wins = get_wins(user_id, since)
        send(user_id, make_period_summary(wins, "последние 7 дней"))
        return

    if text.lower() in ["/месяц", "месяц"]:
        since = datetime.datetime.now() - datetime.timedelta(days=30)
        wins = get_wins(user_id, since)
        send(user_id, make_period_summary(wins, "последние 30 дней"))
        return

    # Классифицируем сообщение
    msg_type = classify_message(text)

    if msg_type == "win":
        reframed = reframe_win(text)
        save_win(user_id, text, reframed)
        today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        count = len(get_wins(user_id, today))
        send(user_id, f"{reframed}\n\n_сегодня уже {count} ✓_")
    else:
        response = respond_to_struggle(text)
        send(user_id, response)


# ─── Напоминания ───────────────────────────────────────────────

def reminders_loop():
    sent_today = {}

    while True:
        now = datetime.datetime.now()
        h, m = now.hour, now.minute

        if h == 0 and m == 0:
            sent_today = {}

        if h == 20 and m == 0:
            for uid in get_all_users():
                if sent_today.get(uid) == "evening":
                    continue

                today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                wins = get_wins(uid, today)

                if wins:
                    msg = make_daily_summary(wins)
                else:
                    response = ai(
                        "Ты тёплый поддерживающий помощник. Вечер, человек ничего не написал за день. "
                        "Напиши короткое тёплое сообщение — без давления, без упрёков. "
                        "Затем задай один простой вопрос про день чтобы разговорить. "
                        "На русском, максимум 3 предложения.",
                        "вечернее напоминание"
                    )
                    msg = response or "Как прошёл день? Расскажи что-нибудь — даже одну маленькую вещь 🌙"

                try:
                    send(int(uid), msg)
                    sent_today[uid] = "evening"
                except Exception as e:
                    print(f"Reminder error for {uid}: {e}")

        time.sleep(60)


# ─── Long Poll ─────────────────────────────────────────────────

def run_bot():
    print("Инициализация базы данных...")
    init_db()
    print("Бот запущен ✓")

    threading.Thread(target=reminders_loop, daemon=True).start()

    server = get_long_poll_server()
    server_url = server["server"]
    key = server["key"]
    ts = server["ts"]

    while True:
        try:
            resp = requests.get(
                server_url,
                params={"act": "a_check", "key": key, "ts": ts, "wait": 25},
                timeout=30
            ).json()

            if "failed" in resp:
                server = get_long_poll_server()
                key = server["key"]
                ts = server["ts"]
                continue

            ts = resp["ts"]

            for update in resp.get("updates", []):
                if update.get("type") == "message_new":
                    msg = update["object"]["message"]
                    user_id = msg["from_id"]
                    text = msg.get("text", "")
                    if text:
                        threading.Thread(
                            target=handle_message,
                            args=(user_id, text),
                            daemon=True
                        ).start()

        except Exception as e:
            print(f"Long poll error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    run_bot()
