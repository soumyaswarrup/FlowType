# FlowType privacy policy

FlowType is a voice-typing app. This page explains exactly what leaves your computer.

## Stays on your computer
- **Your voice.** Audio is recorded only while you hold the hotkey (or use hands-free mode) and is turned into text **locally** by the Whisper speech model. Audio is never uploaded or saved.
- **Your history, settings, snippets and learned words.** Saved only on your computer (`history.jsonl`, `config.json`, in the FlowType folder or `%APPDATA%\FlowType`). You can delete them at any time and switch history off in the settings.
- **Keyboard.** FlowType watches only its own shortcut keys (e.g. Ctrl+Alt) to know when to listen. It does not record or store what you type.

## Sent over the internet (only with these features, each can be switched off)
| Feature | What is sent | To whom | How to turn it off |
|---|---|---|---|
| Grammar check (on by default) | The text of each dictation | [LanguageTool](https://languagetool.org/legal/privacy) (`api.languagetool.org`) | Tray menu → untick **Grammar check** |
| Command mode (off until you choose an AI) | The instruction you speak and the text you selected | The AI service you pick: Groq, Anthropic (Claude), or none if you use Ollama, which runs on your computer | Tray menu → **Command mode AI → Off** |
| First start | A one-time download of the speech model | Hugging Face (download only, nothing about you is sent) | n/a |

FlowType has no accounts, no analytics, no telemetry and no ads. The FlowType project does not run any server and never receives your data.

## Contact
Questions: open an issue at https://github.com/soumyaswarrup/FlowType/issues
