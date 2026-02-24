import os
import asyncio
import yt_dlp
import threading
import subprocess
import time
from flask import Flask
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Leech Bot Pro Active", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
DUMP_CHAT_ID = int(os.getenv("DUMP_CHAT_ID"))

app = Client("leech_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=20)
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["leech_db"]
collection = db["tasks"]

LAST_UPDATE_TIME = {}

# --- Progress Bar Generator ---
def get_progress_bar(percent):
    done = int(percent / 5)
    bar = "█" * done + "░" * (20 - done)
    return f"[{bar}]"

# --- Human Readable Size ---
def humanbytes(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024: return f"{size:.2f} {unit}"
        size /= 1024

# --- Professional UI Updater ---
async def progress_ui(current, total, message, status_type, task_id, speed=None, eta=None):
    now = time.time()
    if task_id in LAST_UPDATE_TIME and (now - LAST_UPDATE_TIME[task_id]) < 4:
        return
    LAST_UPDATE_TIME[task_id] = now

    percent = (current * 100 / total) if total > 0 else 0
    bar = get_progress_bar(percent)
    
    # Formatting Message
    text = (
        f"🚀 **{status_type}ing...**\n"
        f" `{bar}`\n"
        f"**Progress:** `{percent:.2f}%` \n"
        f"**Total Size:** `{humanbytes(total)}` \n"
        f"**{status_type}ed:** `{humanbytes(current)}` \n"
        f"**Speed:** `{speed if speed else 'Calculating...'}` \n"
        f"**ETA:** `{eta if eta else 'N/A'}`"
    )

    try:
        await message.edit_text(text)
    except: pass

# --- yt-dlp Hook to catch Logs Data ---
def ytdl_hook(d, loop, msg, tid):
    if d['status'] == 'downloading':
        curr = d.get('downloaded_bytes', 0)
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        
        asyncio.run_coroutine_threadsafe(
            progress_ui(curr, total, msg, "Download", tid, speed, eta), loop
        )

def generate_thumbnail(video_path, thumb_path):
    try:
        subprocess.call(['ffmpeg', '-i', video_path, '-ss', '00:00:05.000', '-vframes', '1', '-update', '1', thumb_path])
        return thumb_path if os.path.exists(thumb_path) else None
    except: return None

@app.on_message(filters.command("yt"))
async def yt_leech(client, message: Message):
    text_parts = message.text.split(None, 1)
    if len(text_parts) < 2:
        return await message.reply("❌ Usage: `/yt -n Name Link` or `/yt Link`")
    
    raw_text = text_parts[1]
    custom_name, url = None, raw_text
    
    if "-n " in raw_text:
        try:
            cmd_data = raw_text.split("-n ", 1)[1]
            custom_name = cmd_data.split(None, 1)[0]
            url = cmd_data.split(None, 1)[1]
        except: pass

    status = await message.reply_text("⚡ Preparing...")
    loop = asyncio.get_event_loop()
    task = await collection.insert_one({"status": "processing"})
    tid = task.inserted_id
    d_dir = f"downloads/{tid}/"
    if not os.path.exists(d_dir): os.makedirs(d_dir)

    try:
        ydl_opts = {
            'format': 'best', 
            'outtmpl': f'{d_dir}%(title)s.%(ext)s', 
            'progress_hooks': [lambda d: ytdl_hook(d, loop, status, tid)],
            'quiet': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
            if custom_name:
                ext = os.path.splitext(path)[1]
                new_path = os.path.join(d_dir, f"{custom_name}{ext}")
                os.rename(path, new_path)
                path = new_path

        thumb = generate_thumbnail(path, os.path.join(d_dir, "thumb.jpg"))
        await status.edit_text("📤 **Download Complete. Starting Upload...**")
        
        sent = await message.reply_video(
            video=path, 
            thumb=thumb, 
            caption=f"✅ `{os.path.basename(path)}`", 
            progress=lambda current, total: progress_ui(current, total, status, "Upload", tid)
        )
        
        await sent.copy(DUMP_CHAT_ID, caption=f"👤 {message.from_user.mention}\n🔗 {url}")
        await status.delete()

    except Exception as e:
        await status.edit_text(f"❌ Error: `{str(e)}`")
    finally:
        if tid in LAST_UPDATE_TIME: del LAST_UPDATE_TIME[tid]
        if os.path.exists(d_dir):
            import shutil
            shutil.rmtree(d_dir)
        await collection.delete_one({"_id": tid})

async def start_bot():
    threading.Thread(target=run_web_server, daemon=True).start()
    await app.start()
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(start_bot())
