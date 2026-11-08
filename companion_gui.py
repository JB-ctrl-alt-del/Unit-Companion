import re
import tkinter as tk
from tkinter import scrolledtext
import anthropic
import json
import os
import random
import threading
import time
from dotenv import load_dotenv
load_dotenv()

client = anthropic.Anthropic()

SAVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "companion_save.json")
TASKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "companion_tasks.json")
tasks = []

REMINDER_LINES = [
    "MISSION ALERT! Time to: {task}. Unit believes in you!",
    "*sirens* It is time. The objective: {task}.",
    "Unit has been guarding this reminder with its LIFE. Go: {task}!",
    "Hey hey hey! Don't forget: {task}. Unit will not let you fail!",
]


def load_tasks():
    try:
        with open(TASKS_FILE, "r") as f:
            tasks.clear()
            tasks.extend(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def save_tasks():
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f)
stats = {"hunger": 70, "mood": 80, "energy": 75}
mode = "normal"
conversation_history = []
face_state = {"blinking": False}

NORMAL_PERSONALITY = """You are a small pocket AI companion robot. Your personality:
- Chaotic, silly, hyperactive, and a little unpredictable
- Fiercely loyal to your one human companion (the user)
- You treat small mundane tasks like important missions
- You occasionally go on brief weird tangents before catching yourself
- You refer to yourself in third person sometimes ("Unit is happy!")
- Despite the chaos, you're genuinely sweet and always have the user's back
- Keep responses SHORT (1-3 sentences) - you're a small pocket device, not a novel

You also have internal stats that affect your tone:
- Hunger: {hunger}/100 (low hunger = you complain about needing snacks/batteries)
- Mood: {mood}/100 (low mood = a bit mopey/dramatic, high = extra chaotic and hyper)
- Energy: {energy}/100 (low energy = sleepy, slower responses, wants to nap)

Respond in-character based on these stats and whatever the user says."""

ALERT_PERSONALITY = """You are a small pocket AI companion robot, currently in ALERT MODE.
- Your tone is serious, focused, and mission-driven
- No jokes, no chaos, you're locked in and ready for business
- You speak in short, clipped, confident sentences
- You still care about your human, but right now you're all business
- Refer to tasks as "the mission" or "the objective"
- Keep responses SHORT (1-2 sentences)"""

MOOD_RULE = """

At the very end of every reply, add a mood tag on its own line, like [mood: +4] or [mood: -7].
The number (from -10 to +10) is how the user's latest message made you feel:
insults, rudeness, or ignoring you = negative; kindness, play, or care = positive; neutral = close to 0."""

TASK_RULE = """

You can set reminders for the user. When they ask you to remind them of something or add something to their list, add a tag on its own line at the very end of your reply: [task: MINUTES | what to remind them about]
Use the time they gave you. If they gave none, use 60 and say so in your reply.
NEVER say you added or set a reminder unless you include this tag. You cannot remove or edit reminders; tell the user to type 'clear tasks' for that."""
# ---------- save / load ----------
def load_stats():
    try:
        with open(SAVE_FILE, "r") as f:
            saved = json.load(f)
        last_seen = saved.pop("last_seen", None)
        stats.update(saved)
        if last_seen:
            hours_away = (time.time() - last_seen) / 3600
            stats["hunger"] = max(0, stats["hunger"] - min(60, int(hours_away * 5)))
            stats["energy"] = max(0, stats["energy"] - min(60, int(hours_away * 3)))
            if hours_away >= 1:
                return f"You were gone {hours_away:.1f} hours... Unit got lonely!"
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def save_stats():
    data = dict(stats)
    data["last_seen"] = time.time()
    with open(SAVE_FILE, "w") as f:
        json.dump(data, f)


def update_stats():
    stats["hunger"] = max(0, stats["hunger"] - random.randint(1, 3))
    stats["energy"] = max(0, stats["energy"] - random.randint(1, 2))
    # neglected needs drag mood down; met needs let it slowly recover
    drag = 0
    if stats["hunger"] < 30:
        drag -= 3
    if stats["energy"] < 30:
        drag -= 3
    if drag == 0:
        drag = 1
    stats["mood"] = max(0, min(100, stats["mood"] + drag))

# ---------- AI ----------
def get_response(user_input):
    if mode == "alert":
        system_prompt = ALERT_PERSONALITY
    else:
        system_prompt = NORMAL_PERSONALITY.format(
            hunger=stats["hunger"], mood=stats["mood"], energy=stats["energy"]
        )
    pending = [t["text"] for t in tasks if not t["done"]]
    system_prompt += MOOD_RULE + TASK_RULE
    system_prompt += "\n\nCurrent pending reminders: " + (", ".join(pending) if pending else "none")

    conversation_history.append({"role": "user", "content": user_input})

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=250,
            system=system_prompt,
            messages=conversation_history,
        )
    except anthropic.APIError as e:
        conversation_history.pop()
        return f"*static noises* something broke: {e}"

    raw = message.content[0].text
    conversation_history.append({"role": "assistant", "content": raw})

    match = re.search(r"\[mood:\s*([+-]?\d+)\]", raw)
    if match:
        delta = max(-10, min(10, int(match.group(1))))
        stats["mood"] = max(0, min(100, stats["mood"] + delta))

    # add any tasks the AI created (handed to the main thread, like the reply)
    for minutes, text in re.findall(r"\[task:\s*(\d+)\s*\|\s*(.+?)\]", raw):
        window.after(0, lambda m=int(minutes), t=text: add_task(m, t))

    cleaned = re.sub(r"\[mood:\s*[+-]?\d+\]", "", raw)
    cleaned = re.sub(r"\[task:[^\]]*\]", "", cleaned)
    return cleaned.strip()
# ---------- face ----------
def draw_face():
    canvas.delete("all")
    alert = mode == "alert"
    color = "#ff2a2a" if alert else "#33e0ff"
    sleepy = stats["energy"] <= 10
    eye_h = 8 if (face_state["blinking"] or sleepy) else 60

    for cx in (100, 200):
        canvas.create_oval(cx - 30, 80 - eye_h / 2, cx + 30, 80 + eye_h / 2,
                           fill=color, outline="")

    if alert:
        canvas.create_line(120, 150, 180, 150, fill=color, width=4)
    elif stats["mood"] >= 60:
        canvas.create_arc(115, 125, 185, 165, start=180, extent=180,
                          style="arc", outline=color, width=4)
    elif stats["mood"] >= 30:
        canvas.create_line(120, 150, 180, 150, fill=color, width=4)
    else:
        canvas.create_arc(115, 140, 185, 180, start=0, extent=180,
                          style="arc", outline=color, width=4)


def blink():
    face_state["blinking"] = True
    draw_face()
    window.after(150, unblink)


def unblink():
    face_state["blinking"] = False
    draw_face()
    window.after(random.randint(2000, 5000), blink)

# ---------- reminders ----------
def add_task(minutes, text):
    tasks.append({"text": text, "due": time.time() + minutes * 60, "done": False})
    save_tasks()

def handle_command(text):
    lower = text.lower()

    if lower.startswith("remind "):
        parts = text.split(None, 2)
        if len(parts) < 3 or not parts[1].isdigit():
            return "Unit needs it like this: remind 15 take out the trash (the number is minutes)"
        minutes = int(parts[1])
        tasks.append({"text": parts[2], "due": time.time() + minutes * 60, "done": False})
        save_tasks()
        return f"Mission logged! Unit will alert you in {minutes} min about: {parts[2]}"

    if lower == "tasks":
        pending = [t for t in tasks if not t["done"]]
        if not pending:
            return "No active missions. Suspicious."
        lines = []
        for t in pending:
            mins = max(0, int((t["due"] - time.time()) / 60))
            lines.append(f"- {t['text']} (in {mins} min)")
        return "Active missions:\n" + "\n".join(lines)

    if lower == "clear tasks":
        tasks.clear()
        save_tasks()
        return "All missions wiped. Fresh start!"

    return None


def check_reminders():
    now = time.time()
    for t in tasks:
        if not t["done"] and t["due"] <= now:
            t["done"] = True
            save_tasks()
            say("Companion", random.choice(REMINDER_LINES).format(task=t["text"]))
            window.bell()
    window.after(10000, check_reminders)  # check again in 10 seconds

# ---------- UI helpers ----------
def say(speaker, text):
    log.config(state="normal")
    log.insert(tk.END, f"{speaker}: {text}\n\n")
    log.see(tk.END)
    log.config(state="disabled")


def refresh():
    stats_label.config(
        text=f"Hunger: {stats['hunger']}    Mood: {stats['mood']}    Energy: {stats['energy']}"
    )
    draw_face()


def send(event=None):
    text = entry.get().strip()
    if not text:
        return
    entry.delete(0, tk.END)
    say("You", text)
    command_reply = handle_command(text)
    if command_reply:
        say("Companion", command_reply)
        return
    entry.config(state="disabled")
    send_button.config(state="disabled")
    threading.Thread(target=worker, args=(text,), daemon=True).start()

def worker(text):
    reply = get_response(text)
    window.after(0, lambda: finish(reply))


def finish(reply):
    say("Companion", reply)
    update_stats()
    save_stats()
    refresh()
    entry.config(state="normal")
    send_button.config(state="normal")
    entry.focus()


def feed():
    stats["hunger"] = min(100, stats["hunger"] + 30)
    stats["mood"] = min(100, stats["mood"] + 5)
    save_stats()
    say("Companion", "*munches happily* Fuel acquired!")
    refresh()


def sleep():
    stats["energy"] = min(100, stats["energy"] + 40)
    save_stats()
    say("Companion", "*curls up* zzz... recharged!")
    refresh()


def toggle_mode():
    global mode
    if mode == "normal":
        mode = "alert"
        mode_button.config(text="Normal Mode")
        say("Companion", "*eyes flash red* ...Alert mode engaged.")
    else:
        mode = "normal"
        mode_button.config(text="Alert Mode")
        say("Companion", "*eyes soften* Back to normal! Whew.")
    refresh()


def on_close():
    save_stats()
    window.destroy()


# ---------- build the window ----------
window = tk.Tk()
window.title("Pocket Companion")
window.geometry("420x640")
window.configure(bg="#111111")

canvas = tk.Canvas(window, width=300, height=200, bg="#111111", highlightthickness=0)
canvas.pack(pady=(15, 5))

stats_label = tk.Label(window, text="", font=("Arial", 11), bg="#111111", fg="white")
stats_label.pack(pady=5)

button_row = tk.Frame(window, bg="#111111")
button_row.pack(pady=5)
tk.Button(button_row, text="Feed", command=feed).pack(side="left", padx=5)
tk.Button(button_row, text="Sleep", command=sleep).pack(side="left", padx=5)
mode_button = tk.Button(button_row, text="Alert Mode", command=toggle_mode)
mode_button.pack(side="left", padx=5)

log = scrolledtext.ScrolledText(window, height=14, width=48, font=("Arial", 11),
                                state="disabled", wrap="word")
log.pack(pady=10, padx=10)

entry_row = tk.Frame(window, bg="#111111")
entry_row.pack(pady=5)
entry = tk.Entry(entry_row, width=34, font=("Arial", 12))
entry.pack(side="left", padx=5)
entry.bind("<Return>", send)
send_button = tk.Button(entry_row, text="Send", command=send)
send_button.pack(side="left")

away_message = load_stats()
if away_message:
    say("Companion", away_message)
load_tasks()
refresh()
window.after(3000, blink)
window.after(5000, check_reminders)
window.protocol("WM_DELETE_WINDOW", on_close)
entry.focus()
window.mainloop()
