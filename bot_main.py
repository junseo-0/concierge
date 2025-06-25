from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import os, json, datetime, time, schedule, requests, asyncio
from dotenv import load_dotenv
import threading
import openai

# ✅ 환경 변수 로드
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")
openai.api_key = OPENAI_API_KEY

TASK_FILE = "monthly_tasks.json"
user_states = {}

# ✅ GPT Assistant API 호출
async def ask_gpt_assistant(message: str) -> str:
    try:
        thread = openai.beta.threads.create()
        openai.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=message
        )
        run = openai.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
        )
        while True:
            status = openai.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            if status.status == "completed":
                break
            time.sleep(1)
        messages = openai.beta.threads.messages.list(thread_id=thread.id)
        for msg in reversed(messages.data):
            if msg.role == "assistant":
                return msg.content[0].text.value
        return "GPT 응답을 찾을 수 없습니다."
    except Exception as e:
        return f"❌ GPT 오류: {str(e)}"

# ✅ /add 명령어로 일정 등록 시작
async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_states[chat_id] = {"step": "company"}
    await update.message.reply_text("✅ [1/3] 회사명을 입력해주세요:")

# ✅ /view 명령어로 일정 확인
async def view_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await show_tasks(chat_id, update)

# ✅ /delete 명령어로 일정 삭제 시작
async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not os.path.exists(TASK_FILE):
        return await update.message.reply_text("❗ 삭제할 일정이 없습니다.")
    with open(TASK_FILE, "r", encoding="utf-8") as f:
        tasks = json.load(f)
    user_tasks = [t for t in tasks if t["chat_id"] == chat_id]
    if not user_tasks:
        return await update.message.reply_text("❗ 등록된 일정이 없습니다.")

    keyboard = [
        [InlineKeyboardButton(f"{t['day']}일: {t['company']} / {t['task']}", callback_data=f"delete:{i}")]
        for i, t in enumerate(user_tasks)
    ]
    await update.message.reply_text("🗑 삭제할 일정을 선택하세요:", reply_markup=InlineKeyboardMarkup(keyboard))

# ✅ 버튼 클릭 처리 (추가 등록/삭제)
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = str(query.message.chat.id)
    await query.answer()

    if query.data.startswith("delete:"):
        index = int(query.data.split(":")[1])
        with open(TASK_FILE, "r", encoding="utf-8") as f:
            tasks = json.load(f)
        user_tasks = [t for t in tasks if t["chat_id"] == chat_id]
        if index >= len(user_tasks):
            return await query.edit_message_text("❗ 유효하지 않은 선택입니다.")
        target = user_tasks[index]
        tasks.remove(target)
        with open(TASK_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2, ensure_ascii=False)
        return await query.edit_message_text(f"✅ 삭제 완료: {target['day']}일 {target['company']} / {target['task']}")

    elif query.data == "add_task_again":
        user_states[chat_id] = {"step": "company"}
        await query.edit_message_text("✅ [1/3] 회사명을 입력해주세요:")

# ✅ 메시지 핸들러 (상태 기반 일정 등록 + GPT 응답)
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()

    if chat_id in user_states:
        state = user_states[chat_id]

        if state["step"] == "company":
            state["company"] = text
            state["step"] = "day"
            await update.message.reply_text("✅ [2/3] 반복할 날짜를 숫자로 입력해주세요 (예: 10)")

        elif state["step"] == "day":
            if not text.isdigit() or not (1 <= int(text) <= 31):
                return await update.message.reply_text("❗ 1~31 사이의 숫자를 입력해주세요.")
            state["day"] = int(text)
            state["step"] = "task"
            await update.message.reply_text("✅ [3/3] 업무 내용을 입력해주세요:")

        elif state["step"] == "task":
            state["task"] = text
            task = {
                "chat_id": chat_id,
                "company": state["company"],
                "day": state["day"],
                "task": state["task"],
                "message": f"[{state['company']}] {state['day']}일 {state['task']} 일정입니다. 확인 바랍니다.",
                "remind_before": 1
            }
            tasks = []
            if os.path.exists(TASK_FILE):
                with open(TASK_FILE, "r", encoding="utf-8") as f:
                    tasks = json.load(f)
            tasks.append(task)
            with open(TASK_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, indent=2, ensure_ascii=False)

            user_states.pop(chat_id, None)
            keyboard = [[InlineKeyboardButton("➕ 추가 등록", callback_data="add_task_again")]]
            await update.message.reply_text(f"✅ 등록 완료!\n{task['message']}", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("⏳ GPT 응답 중...")
        gpt_response = await ask_gpt_assistant(text)
        await update.message.reply_text(gpt_response)

# ✅ 내 일정 조회
async def show_tasks(chat_id: str, query_or_update):
    if not os.path.exists(TASK_FILE):
        return await query_or_update.reply_text("등록된 일정이 없습니다.")
    with open(TASK_FILE, "r", encoding="utf-8") as f:
        tasks = json.load(f)
    user_tasks = [t for t in tasks if t["chat_id"] == chat_id]
    if not user_tasks:
        await query_or_update.reply_text("등록된 일정이 없습니다.")
    else:
        message = "📅 등록된 반복 일정 목록:\n"
        for t in user_tasks:
            message += f"- {t['day']}일: {t['company']} / {t['task']}\n"
        await query_or_update.reply_text(message)

# ✅ 자동 리마인드 전송
def send_reminder(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    requests.post(url, data=payload)

def check_and_remind():
    today = datetime.datetime.today()
    if not os.path.exists(TASK_FILE):
        return
    with open(TASK_FILE, "r", encoding="utf-8") as f:
        tasks = json.load(f)
    for task in tasks:
        remind_day = task["day"] - task.get("remind_before", 1)
        if remind_day <= 0:
            continue
        if today.day == remind_day:
            send_reminder(task["chat_id"], task["message"])

# ✅ 스케줄러 시작
def run_scheduler():
    schedule.every().day.at("06:00").do(check_and_remind)
    print("🔔 리마인더 스케줄러 실행 중...")
    while True:
        schedule.run_pending()
        time.sleep(60)

# ✅ 봇 명령어 메뉴 설정
async def setup_bot_commands(app):
    commands = [
        BotCommand("add", "일정 등록 시작"),
        BotCommand("view", "일정 목록 확인"),
        BotCommand("delete", "일정 삭제")
    ]
    await app.bot.set_my_commands(commands)

# ✅ 봇 실행 함수
def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("view", view_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    asyncio.run(setup_bot_commands(app))
    print("🤖 챗봇 실행 중...")
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_scheduler, daemon=True).start()
    run_bot()