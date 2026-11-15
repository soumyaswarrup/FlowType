# FlowType 🎙️ — talk instead of typing (Windows)

Hold a key, speak, and your words are typed into **any app**: WhatsApp Web, Gmail, Outlook, Word, Slack, ChatGPT, Claude…
Speech recognition runs **offline on your PC** (OpenAI Whisper via faster-whisper). Free, no account needed.

![FlowType on-screen indicator](screenshot.png)

## ⬇️ Download
1. Go to **[Releases](../../releases/latest)** and download **`FlowType-Windows.zip`**.
2. Unzip it and double-click **`FlowType.exe`**. It installs itself, adds a Desktop icon and starts with Windows.
   - If Windows says *"Windows protected your PC"*, click **More info → Run anyway** (the app isn't code-signed).
3. The first launch downloads the speech model (~500 MB) — give it a few minutes.

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

## 🛠️ Run or build from source
Requires Windows 10/11 and Python 3.10+.
```bat
setup.bat        :: creates .venv, installs packages, downloads the model, starts FlowType
build-exe.bat    :: builds dist\FlowType-Windows.zip (the shareable app)
start-debug.bat  :: runs with a console window to see errors
```
Pushing a tag like `v1.0.0` makes GitHub Actions build the exe and publish it on the Releases page automatically.

## 🔒 Privacy
- Voice → text happens **locally**; audio never leaves your PC.
- Grammar check sends the **text** to LanguageTool (can be turned off).
- History is saved only on your PC (`%APPDATA%\FlowType\history.jsonl`).

## License
MIT
