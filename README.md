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
| `enable-gpu.bat` | Optional: use an NVIDIA GPU for faster text |
| `remove-from-startup.bat` | Stop FlowType starting with Windows |

## 🗣️ How to use
| Do this | What happens |
|---|---|
| **Hold `Ctrl + Alt`**, speak, release | Your words are typed where the cursor is (you see them live while you talk) |
| **`Ctrl + Shift + Space`** | Hands-free: press once to start, again to stop |
| End with **"send it"** / "send it now" / "forward it" / "… Send." | Types the message **and sends it** (Enter; Ctrl+Enter in Gmail/Outlook) |
| Say **"new line"** / **"new paragraph"** | Line / paragraph break |
| Say **"scratch that"** | Deletes the sentence you just said |
| Say **"insert my signature"** | Pastes a saved snippet (see below) |
| Select text, **hold `Ctrl + Alt + Shift`**, say *"make this more formal"* | **Command mode** — rewrites the selection (needs an AI, see below) |
| Select a word, press **`Ctrl + Alt + D`** | Teaches FlowType that word / correction |

Filler words (um, uh) are removed automatically.

## ✨ Features

### 1. Command mode — edit by voice
Select any text, **hold `Ctrl + Alt + Shift`** and say what to do: *"make this more formal"*, *"shorten this"*, *"turn this into bullet points"*, *"translate to Hindi"*, *"reply to this politely"*. The selection is replaced with the result (Ctrl+Z undoes it).
With nothing selected, it writes new text: *"write a two-line thank-you note to Rahul"*.
The mic dot turns **amber** in command mode.

Command mode needs an AI. Pick one in the tray menu → **Command mode AI**:
- **Ollama (free, private, on your PC)**: install from [ollama.com](https://ollama.com), then run `ollama pull llama3.2`.
- **Groq (free API key)**: get a key at [console.groq.com/keys](https://console.groq.com/keys).
- **Claude (Anthropic API key)**: get a key at [console.anthropic.com](https://console.anthropic.com).
With Groq or Claude, the selected text and your instruction are sent to that service.

### 2. Voice snippets
Say **"insert my signature"** (or "paste my email address", etc.) and saved text is pasted. Edit them in the tray → **Edit snippets, words & settings** → the `"snippets"` section:
```json
"snippets": {
  "signature": "Best regards,\nSoumya Swarup Sahoo",
  "email address": "you@example.com",
  "intro": "Thanks for reaching out! ..."
}
```

### 3. Learns your words
If a name or term comes out wrong (e.g. *seem* instead of **SIEM**), fix it in the text, **select the correct word** and press **`Ctrl + Alt + D`**.
FlowType remembers the spelling and auto-corrects it from then on ("Learned: seem → SIEM"). Selecting any word and pressing `Ctrl + Alt + D` also adds it to your vocabulary, which helps recognition.

### 4. Choose your tone
Right-click the purple mic → **Tone** and pick how you want to sound. Everything you dictate is written that way:

| Tone | What you get | Example: *"hey I'm gonna send u the report asap, thanks"* |
|---|---|---|
| **Auto** (default) | Matches the app: casual in chats, professional in email & docs, code in editors | depends on the app |
| **Casual** | Contractions, relaxed, no stiff full stop | Hey I'm gonna send u the report asap, thanks |
| **Professional** | No slang or contractions, full sentences | Hello, I am going to send you the report as soon as possible, thank you. |
| **Code** | No capitals/full stops; *"dot"*, *"dash dash"*, *"slash"*, *"open paren"* become symbols | *"python main dot py dash dash help"* → `python main.py --help` |
| **As spoken** | Just your words cleaned of um/uh, no grammar changes | Hey I'm gonna send u the report asap, thanks. |

The pill shows your current tone while you talk (e.g. "Listening · Professional"). Email layout in Gmail/Outlook still applies in any tone.

### 5. Uses your NVIDIA GPU automatically
If your PC has an NVIDIA graphics card, FlowType uses it and text appears several times faster. Running from source? Double-click **`enable-gpu.bat`** once to install the GPU libraries. The tray menu shows **Ready (GPU)** or **Ready (CPU)**.

### 6. Live preview
While you hold the key, the words you're saying appear in the on-screen pill as you speak, so you know it's hearing you right.

### ✍️ Grammar check
Clear mistakes are fixed before typing (*"I has completed"* → *"I have completed"*). When there's more than one possible fix, a small popup suggests it instead of guessing. Uses the free [LanguageTool](https://languagetool.org) service, so the **dictated text is sent to LanguageTool** for checking. You can turn it off in the tray menu.

### ⚙️ Settings
Click the **^** arrow next to the clock → **right-click the purple mic**: command mode AI, tone, live preview, grammar check, email formatting, auto-send, snippets & words, history, quit.

## 🛠️ For developers
Python app (`flowtype.py` = tray app, hotkeys, recording, overlay, command mode; `textproc.py` = clean-up, "send it", grammar, email layout, snippets, tone per app, AI calls).
Publishing a release on GitHub (e.g. `v1.0.1`) makes GitHub Actions build the exe and attach `FlowType-Windows.zip` to it automatically.

## 🔒 Privacy
- Voice → text happens **locally**; audio never leaves your PC.
- Grammar check sends the **text** to LanguageTool (can be turned off).
- Command mode with Groq/Claude sends the selected text + instruction to that AI; with Ollama everything stays on your PC.
- History is saved only on your PC (`%APPDATA%\FlowType\history.jsonl`).

## License
MIT
