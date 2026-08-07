from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
import json
import uuid
import time
import os
from datetime import datetime
from typing import Dict, Set

app = FastAPI()

# Хранилища
users: Dict[str, dict] = {}
chats: Dict[str, dict] = {}
sessions: Dict[str, str] = {}
contacts: Dict[str, list] = {}
folders: Dict[str, list] = {}
folder_names: Dict[str, dict] = {}
media_files: Dict[str, dict] = {}
active_connections: Dict[str, Set[WebSocket]] = {}
user_stats: Dict[str, dict] = {}
deleted_messages: set = set()
user_deleted: Dict[str, set] = {}
last_seen: Dict[str, float] = {}

def generate_id():
    return str(uuid.uuid4())[:8]

def get_user_by_username(username: str):
    for uid, data in users.items():
        if data["username"].lower() == username.lower():
            return uid, data
    return None, None

def get_user_by_session(session_token: str):
    if session_token in sessions:
        uid = sessions[session_token]
        if uid in users:
            return uid, users[uid]
    return None, None

def get_chat_messages(chat_id: str, user_id: str):
    if chat_id not in chats:
        return []
    chat = chats[chat_id]
    messages = chat.get("messages", [])
    user_deleted_set = user_deleted.get(user_id, set())
    return [m for m in messages if m["id"] not in user_deleted_set and m["id"] not in deleted_messages]

def save_message(chat_id: str, message: dict):
    if chat_id not in chats:
        return
    chats[chat_id]["messages"].append(message)
    uid = message.get("from")
    if uid:
        if uid not in user_stats:
            user_stats[uid] = {"messages": 0, "chats": 0, "days": 0, "joined": datetime.now().isoformat()}
        user_stats[uid]["messages"] = user_stats[uid].get("messages", 0) + 1
        user_chats = set()
        for cid, chat in chats.items():
            if uid in chat.get("members", []):
                user_chats.add(cid)
        user_stats[uid]["chats"] = len(user_chats)
        if "joined" in user_stats[uid]:
            joined = datetime.fromisoformat(user_stats[uid]["joined"])
            user_stats[uid]["days"] = (datetime.now() - joined).days

async def broadcast_message(chat_id: str, message: dict):
    if chat_id not in active_connections:
        return
    for conn in active_connections.get(chat_id, set()):
        try:
            await conn.send_text(json.dumps(message))
        except:
            pass

# ============= API =============
@app.get("/")
async def get_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.post("/api/register")
async def register(request: Request):
    data = await request.json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    name = data.get("name", "").strip() or username

    if not username or not password:
        return JSONResponse({"error": "Заполните все поля"}, status_code=400)

    existing_uid, _ = get_user_by_username(username)
    if existing_uid:
        return JSONResponse({"error": "Пользователь уже существует"}, status_code=400)

    uid = generate_id()
    users[uid] = {
        "id": uid,
        "name": name,
        "username": username,
        "password": password,
        "avatar": name[0].upper() if name else "U",
        "color": "linear-gradient(135deg,#8a6afa,#5a4a9a)",
        "online": False
    }

    favorites_id = generate_id()
    chats[favorites_id] = {
        "id": favorites_id,
        "name": "Избранное",
        "type": "favorites",
        "members": [uid],
        "messages": [],
        "created": datetime.now().isoformat()
    }

    contacts[uid] = []
    folders[uid] = []
    folder_names[uid] = {}
    user_deleted[uid] = set()
    user_stats[uid] = {"messages": 0, "chats": 0, "days": 0, "joined": datetime.now().isoformat()}

    session_token = generate_id() + generate_id()
    sessions[session_token] = uid
    last_seen[uid] = time.time()

    return JSONResponse({
        "success": True,
        "session": session_token,
        "user": users[uid]
    })

@app.post("/api/login")
async def login(request: Request):
    data = await request.json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    uid, user = get_user_by_username(username)
    if not uid or user["password"] != password:
        return JSONResponse({"error": "Неверный логин или пароль"}, status_code=400)

    session_token = generate_id() + generate_id()
    sessions[session_token] = uid
    user["online"] = True
    last_seen[uid] = time.time()

    return JSONResponse({
        "success": True,
        "session": session_token,
        "user": user
    })

@app.post("/api/logout")
async def logout(request: Request):
    data = await request.json()
    session_token = data.get("session")
    if session_token in sessions:
        uid = sessions[session_token]
        if uid in users:
            users[uid]["online"] = False
            last_seen[uid] = time.time()
        del sessions[session_token]
    return JSONResponse({"success": True})

@app.get("/api/me")
async def get_me(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, user = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    return JSONResponse({"user": user})

@app.get("/api/chats")
async def get_chats(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    result = []
    for cid, chat in chats.items():
        if uid in chat.get("members", []):
            name = chat["name"]
            avatar = "💬"
            color = "linear-gradient(135deg,#6a7a96,#4a5a7a)"
            if chat["type"] == "favorites":
                name = "Избранное"
                avatar = "⭐"
                color = "linear-gradient(135deg,#fbbf24,#f59e0b)"
            elif chat["type"] == "group":
                avatar = "👥"
                color = "linear-gradient(135deg,#34d399,#10b981)"
            elif chat["type"] == "channel":
                avatar = "📢"
                color = "linear-gradient(135deg,#f472b6,#ec4899)"
            msgs = get_chat_messages(cid, uid)
            last_msg = msgs[-1]["text"] if msgs else "Нет сообщений"
            last_time = msgs[-1]["time"] if msgs else ""
            unread = False
            for m in msgs:
                if m.get("from") != uid and m.get("read", False) is False:
                    unread = True
                    break
            result.append({
                "id": cid,
                "name": name,
                "avatar": avatar,
                "color": color,
                "last_message": last_msg,
                "last_time": last_time,
                "online": chat.get("online", True),
                "is_favorites": chat["type"] == "favorites",
                "is_group": chat["type"] == "group",
                "is_channel": chat["type"] == "channel",
                "unread": unread
            })
    return JSONResponse({"chats": result})

@app.get("/api/chat/{chat_id}/messages")
async def get_messages(request: Request, chat_id: str):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    if chat_id not in chats:
        return JSONResponse({"error": "Чат не найден"}, status_code=404)
    if uid not in chats[chat_id]["members"]:
        return JSONResponse({"error": "Нет доступа"}, status_code=403)

    msgs = get_chat_messages(chat_id, uid)
    for m in msgs:
        if m.get("from") != uid:
            m["read"] = True
    return JSONResponse({"messages": msgs})

@app.post("/api/chat/{chat_id}/messages/{message_id}/edit")
async def edit_message(request: Request, chat_id: str, message_id: str):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    data = await request.json()
    new_text = data.get("text", "").strip()
    if not new_text:
        return JSONResponse({"error": "Текст не может быть пустым"}, status_code=400)

    if chat_id not in chats:
        return JSONResponse({"error": "Чат не найден"}, status_code=404)
    chat = chats[chat_id]
    for msg in chat["messages"]:
        if msg["id"] == message_id and msg["from"] == uid:
            msg["text"] = new_text
            msg["edited"] = True
            msg["edited_time"] = datetime.now().strftime("%H:%M")
            await broadcast_message(chat_id, {
                "type": "message_edited",
                "message_id": message_id,
                "text": new_text,
                "edited_time": msg["edited_time"]
            })
            return JSONResponse({"success": True})
    return JSONResponse({"error": "Сообщение не найдено"}, status_code=404)

@app.post("/api/chat/{chat_id}/messages/{message_id}/delete")
async def delete_message(request: Request, chat_id: str, message_id: str):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    data = await request.json()
    for_all = data.get("for_all", False)

    if chat_id not in chats:
        return JSONResponse({"error": "Чат не найден"}, status_code=404)
    chat = chats[chat_id]
    for msg in chat["messages"]:
        if msg["id"] == message_id:
            if for_all:
                deleted_messages.add(message_id)
                await broadcast_message(chat_id, {
                    "type": "message_deleted",
                    "message_id": message_id,
                    "for_all": True
                })
            else:
                if uid not in user_deleted:
                    user_deleted[uid] = set()
                user_deleted[uid].add(message_id)
                await broadcast_message(chat_id, {
                    "type": "message_deleted",
                    "message_id": message_id,
                    "for_all": False
                })
            return JSONResponse({"success": True})
    return JSONResponse({"error": "Сообщение не найдено"}, status_code=404)

@app.post("/api/chat/{chat_id}/messages/{message_id}/reply")
async def reply_to_message(request: Request, chat_id: str, message_id: str):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    data = await request.json()
    text = data.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Текст не может быть пустым"}, status_code=400)

    if chat_id not in chats:
        return JSONResponse({"error": "Чат не найден"}, status_code=404)
    chat = chats[chat_id]
    original_msg = None
    for msg in chat["messages"]:
        if msg["id"] == message_id:
            original_msg = msg
            break
    if not original_msg:
        return JSONResponse({"error": "Сообщение не найдено"}, status_code=404)

    reply_msg = {
        "id": generate_id(),
        "text": text,
        "from": uid,
        "from_name": users[uid]["name"],
        "time": datetime.now().strftime("%H:%M"),
        "timestamp": time.time(),
        "reply_to": message_id,
        "reply_text": original_msg.get("text", ""),
        "reply_from": original_msg.get("from_name", "Unknown")
    }
    save_message(chat_id, reply_msg)
    await broadcast_message(chat_id, {"type": "new_message", "message": reply_msg})
    return JSONResponse({"success": True})

@app.get("/api/search")
async def search(request: Request, q: str):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    if not q or len(q) < 2:
        return JSONResponse({"results": []})

    results = []
    for cid, chat in chats.items():
        if uid not in chat.get("members", []):
            continue
        for msg in get_chat_messages(cid, uid):
            if q.lower() in msg.get("text", "").lower():
                results.append({
                    "chat_id": cid,
                    "chat_name": chat["name"],
                    "message": msg,
                    "highlight": q
                })
    return JSONResponse({"results": results})

@app.post("/api/contacts/add")
async def add_contact(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    data = await request.json()
    username = data.get("username", "").strip()
    if not username:
        return JSONResponse({"error": "Введите имя пользователя"}, status_code=400)

    contact_uid, contact_user = get_user_by_username(username)
    if not contact_uid:
        return JSONResponse({"error": "Пользователь не найден"}, status_code=404)
    if contact_uid == uid:
        return JSONResponse({"error": "Нельзя добавить себя"}, status_code=400)

    if uid not in contacts:
        contacts[uid] = []
    if contact_uid not in contacts[uid]:
        contacts[uid].append(contact_uid)
        chat_id = generate_id()
        chats[chat_id] = {
            "id": chat_id,
            "name": f"{users[uid]['name']} & {contact_user['name']}",
            "type": "private",
            "members": [uid, contact_uid],
            "messages": [],
            "created": datetime.now().isoformat()
        }
        return JSONResponse({"success": True, "contact": contact_user})
    return JSONResponse({"error": "Контакт уже существует"}, status_code=400)

@app.get("/api/contacts")
async def get_contacts(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    result = []
    for cid in contacts.get(uid, []):
        if cid in users:
            user = users[cid]
            result.append({
                "id": cid,
                "name": user["name"],
                "username": user["username"],
                "avatar": user["avatar"],
                "online": user.get("online", False),
                "last_seen": last_seen.get(cid, 0)
            })
    return JSONResponse({"contacts": result})

@app.post("/api/folders/create")
async def create_folder(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    data = await request.json()
    name = data.get("name", "Новая папка").strip()
    if not name:
        return JSONResponse({"error": "Введите название"}, status_code=400)

    folder_id = generate_id()
    folders.setdefault(uid, []).append(folder_id)
    folder_names.setdefault(uid, {})[folder_id] = name
    return JSONResponse({"success": True, "folder_id": folder_id, "name": name})

@app.get("/api/folders")
async def get_folders(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    result = []
    for fid in folders.get(uid, []):
        result.append({
            "id": fid,
            "name": folder_names.get(uid, {}).get(fid, "Без названия")
        })
    return JSONResponse({"folders": result})

@app.get("/api/media")
async def get_media(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    result = []
    for fid, media in media_files.items():
        if media["user_id"] == uid:
            result.append(media)
    return JSONResponse({"media": result})

@app.get("/api/stats")
async def get_stats(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    stats = user_stats.get(uid, {"messages": 0, "chats": 0, "days": 0})
    return JSONResponse({"stats": stats})

@app.get("/api/qr")
async def get_qr(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)
    uid, _ = get_user_by_session(session_token)
    if not uid:
        return JSONResponse({"error": "Не авторизован"}, status_code=401)

    qr_data = f"nearby://login?token={generate_id()}&user={uid}"
    return JSONResponse({"qr": qr_data})

# ============= WEBSOCKET =============
@app.websocket("/ws/{chat_id}")
async def websocket_endpoint(websocket: WebSocket, chat_id: str):
    session_token = websocket.query_params.get("session")
    if not session_token:
        await websocket.close(code=1008, reason="Unauthorized")
        return

    uid, user = get_user_by_session(session_token)
    if not uid:
        await websocket.close(code=1008, reason="Unauthorized")
        return

    if chat_id not in chats:
        await websocket.close(code=1008, reason="Chat not found")
        return

    if uid not in chats[chat_id]["members"]:
        await websocket.close(code=1008, reason="Access denied")
        return

    await websocket.accept()

    if chat_id not in active_connections:
        active_connections[chat_id] = set()
    active_connections[chat_id].add(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg_data = json.loads(data)
                msg_type = msg_data.get("type", "text")
                text = msg_data.get("text", "").strip()
                if not text and msg_type != "voice" and msg_type != "file":
                    continue

                dt = datetime.now()
                time_str = dt.strftime("%H:%M")

                message = {
                    "id": generate_id(),
                    "type": msg_type,
                    "text": text if msg_type == "text" else "",
                    "from": uid,
                    "from_name": user["name"],
                    "time": time_str,
                    "timestamp": time.time(),
                    "read": False
                }

                if msg_type == "voice":
                    message["duration"] = msg_data.get("duration", 0)
                elif msg_type == "file":
                    message["filename"] = msg_data.get("filename", "file")
                    message["filetype"] = msg_data.get("filetype", "file")
                    message["filesize"] = msg_data.get("filesize", 0)

                if "reply_to" in msg_data:
                    message["reply_to"] = msg_data["reply_to"]
                    for m in chats[chat_id]["messages"]:
                        if m["id"] == msg_data["reply_to"]:
                            message["reply_text"] = m.get("text", "")
                            message["reply_from"] = m.get("from_name", "Unknown")
                            break

                save_message(chat_id, message)

                for conn in active_connections.get(chat_id, set()):
                    try:
                        await conn.send_text(json.dumps({
                            "type": "new_message",
                            "message": message
                        }))
                    except:
                        pass
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        active_connections[chat_id].discard(websocket)
        if not active_connections[chat_id]:
            del active_connections[chat_id]

# ============= ЗАПУСК (для Railway) =============
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
