# FlowType 🎙️ — talk instead of typing (Windows)

Hold a key, speak, and your words are typed into **any app**: WhatsApp Web, Gmail, Outlook, Word, Slack, ChatGPT, Claude…
Speech recognition runs **offline on your PC** (OpenAI Whisper via faster-whisper). Free, no account needed.

![FlowType on-screen indicator](screenshot.png)

## ⬇️ Install — pick one

### Option A: ready-made app (easiest, no Python needed)
1. Go to **[Releases](../../releases/latest)** and download **`FlowType-Windows.zip`**.
2. Unzip it and double-click **`FlowType.exe`**. It installs itself, adds a Desktop icon and starts with Windows.
   - If Windows says *"Windows protected your PC"*, click **More info → Run anyway** (the app isn't code-signed).
3. The first launch downloads the speech model (~500 MB), so give it a few minutes before your first try.

### Option B: from the source code (Download ZIP or git clone)
1. Get the code, either way:
   - Click the green **Code** button → **Download ZIP**, then unzip it (e.g. to `Documents\FlowType`), **or**
   - `git clone https://github.com/soumyaswarrup/FlowType.git`
2. Open the folder and double-click **`setup.bat`**. It will:
   - find Python 3.10–3.14, or install Python 3.12 for you (via winget) if you don't have it,
   - create a private `.venv` and install the packages,
   - download the speech model (~500 MB, one time),
   - add Desktop / Start-menu shortcuts, set FlowType to start with Windows, and start it.
   Takes about 5 minutes. Details are written to `setup.log`.
3. From then on, start it with the **FlowType** Desktop icon (or `FlowType.bat`).

Keep the folder where it is after setup, because the shortcuts point to it. If something doesn't work, run **`start-debug.bat`** to see the error.

| File | What it does |
|---|---|
| `setup.bat` | One-time install (Option B) |
| `FlowType.bat` | Start / restart FlowType |
| `start-debug.bat` | Run with a console window to see errors |
| `build-exe.bat` | Build your own `FlowType-Windows.zip` (the Option A app) |
| `remove-from-startup.bat` | Stop FlowType starting with Windows |

## 🗣️ How to use
| Do this | What happens |
|---|---|
| **Hold `Ctrl + Alt`**, speak, release | Your words are typed where the cursor is |
| **`Ctrl + Shift + Space`** | Hands-free: press once to start, again to stop |
| End with **"send it"** / "send it now" / "forward it" / "… Send." | Types the message **and sends it** (Enter; Ctrl+Enter in Gmail/Outlook) |
| Say **"new line"** / **"new paragraph"** | Line / paragraph break |
| Say **"scratch that"** | Deletes the sentence you just said |

Filler words (um, uh) are removed automatically.

### ✍️ Grammar check
Clear mistakes are fixed before typing (*"I has completed"* → *"I have completed"*). When there's more than one possible fix, a small popup shows a suggestion instead of guessing.
Uses the free [LanguageTool](https://languagetool.org) service, so the **dictated text is sent to LanguageTool** for checking. You can turn it off.

### 📧 Email formatting
In Gmail / Outlook, dictation is laid out as an email — greeting line, short paragraphs, numbered lists for "first… second… third…", sign-off and name on their own lines.

### ⚙️ Settings
Click the **^** arrow next to the clock → **right-click the purple mic**: grammar check, email formatting, auto-send, settings file, history, quit.

## 🛠️ For developers
Python app (`flowtype.py` = tray app, hotkeys, recording, typing; `textproc.py` = clean-up, "send it", grammar, email layout).
Publishing a release on GitHub (e.g. `v1.0.1`) makes GitHub Actions build the exe and attach `FlowType-Windows.zip` to it automatically.

## 🔒 Privacy
- Voice → text happens **locally**; audio never leaves your PC.
- Grammar check sends the **text** to LanguageTool (can be turned off).
- History is saved only on your PC (`%APPDATA%\FlowType\history.jsonl`).

## License
MIT
