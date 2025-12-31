import os
import time
import base64
import json
import asyncio
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- FAKE WEB SERVER (To Keep Render Happy) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Start the fake server in a separate thread
t = Thread(target=run_web_server)
t.start()

# --- SECRET DECODER (To load keys from Render Env Vars) ---
def decode_key(env_var_name, file_name):
    encoded_data = os.environ.get(env_var_name)
    if encoded_data:
        try:
            decoded = base64.b64decode(encoded_data).decode('utf-8')
            with open(file_name, 'w') as f:
                f.write(decoded)
            print(f"✅ Loaded {file_name} from Environment Variable")
        except Exception as e:
            print(f"❌ Error decoding {env_var_name}: {e}")

# Load secrets from Render Environment Variables
decode_key("TOKEN_JSON_B64", "token.json")
decode_key("CREDENTIALS_JSON_B64", "credentials.json")

# --- CONFIGURATION (Get these from Env Vars too) ---
API_ID = os.environ.get('API_ID')       
API_HASH = os.environ.get('API_HASH')   
BOT_TOKEN = os.environ.get('BOT_TOKEN') 
DRIVE_FOLDER_ID = os.environ.get('DRIVE_FOLDER_ID')

# --- AUTHENTICATION ---
TOKEN_FILE = 'token.json'
creds = None

if os.path.exists(TOKEN_FILE):
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, ['https://www.googleapis.com/auth/drive'])

if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        except:
            print("Token expired and refresh failed.")
    else:
        print("❌ Error: Valid token.json not found.")

if creds:
    drive_service = build('drive', 'v3', credentials=creds)
else:
    print("⚠️ Drive Service not loaded (Auth failed)")

# --- BOT SETUP ---
if API_ID and BOT_TOKEN:
    bot = TelegramClient('bot_session', int(API_ID), API_HASH).start(bot_token=BOT_TOKEN)
else:
    print("❌ API_ID or BOT_TOKEN missing")
    exit()

# --- HELPERS & PROGRESS (Same as before) ---
def human_readable_size(size, decimal_places=2):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.{decimal_places}f}{unit}"
        size /= 1024.0
    return f"{size:.{decimal_places}f}PB"

def get_progress_bar_string(current, total):
    percentage = current / total
    finished_length = int(percentage * 10)
    bar = "■" * finished_length + "□" * (10 - finished_length)
    return f"[{bar}]"

last_update_time = 0

async def progress_callback(current, total, event, title, status_type):
    global last_update_time
    now = time.time()
    if now - last_update_time >= 5 or current == total:
        percentage = (current / total) * 100
        bar = get_progress_bar_string(current, total)
        current_size = human_readable_size(current)
        total_size = human_readable_size(total)
        text = (
            f"**{status_type}**\n"
            f"`📂 {title}`\n"
            f"`{bar} {percentage:.2f}%`\n"
            f"`💾 {current_size} / {total_size}`"
        )
        try:
            await event.edit(text)
            last_update_time = now
        except:
            pass 

@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.reply("👋 **Bot is Online on Render!**\nSend me a file.")

@bot.on(events.NewMessage)
async def handle_file(event):
    if event.file and not event.text.startswith('/'):
        sender = await event.get_sender()
        user_id = sender.id
        async with bot.conversation(user_id) as conv:
            await conv.send_message("📝 **What should be the title?**")
            response = await conv.get_response()
            user_title = response.text.strip()
            
            original_ext = event.file.ext if event.file.ext else ""
            if not user_title.lower().endswith(original_ext.lower()):
                final_filename = f"{user_title}{original_ext}"
            else:
                final_filename = user_title

            status_msg = await conv.send_message(f"⏳ Please wait...")
            global last_update_time
            last_update_time = 0 
            
            # Download
            file_path = await bot.download_media(
                event.message, 
                file=final_filename,
                progress_callback=lambda c, t: progress_callback(c, t, status_msg, final_filename, "⬇️ Downloading...")
            )
            
            # Upload
            file_metadata = {'name': final_filename, 'parents': [DRIVE_FOLDER_ID]}
            media = MediaFileUpload(file_path, resumable=True, chunksize=5*1024*1024)
            try:
                request = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink')
                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        await progress_callback(status.resumable_progress, status.total_size, status_msg, final_filename, "⬆️ Uploading to Drive...")
                file_link = response.get('webViewLink')
                await status_msg.edit(f"✅ **Mission Complete**\n\n📂 **File:** `{final_filename}`\n🔗 **Link:**\n`{file_link}`")
            except Exception as e:
                await status_msg.edit(f"❌ **Error:**\n`{str(e)}`")
            finally:
                if os.path.exists(file_path):
                    os.remove(file_path)

print("Bot is starting...")
bot.run_until_disconnected()