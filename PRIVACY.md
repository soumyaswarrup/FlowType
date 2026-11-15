# FlowType privacy policy

FlowType is a voice-typing app. This page explains exactly what leaves your computer.

## Stays on your computer
- **Your voice.** Audio is recorded only while you hold the hotkey (or use hands-free mode) and is turned into text **locally** by the Whisper speech model. Audio is never uploaded or saved.
- **Your history, settings, snippets and learned words.** Saved only on your computer (`history.jsonl`, `config.json`, in the FlowType folder or `%APPDATA%\FlowType`). You can delete them at any time and switch history off in the settings.
- **Meeting recordings and file transcripts.** The audio is transcribed on your computer and the notes are saved in `Documents\FlowType` (or next to the file you picked). The audio itself is not kept.
- **Read aloud.** Uses your computer's own voice; the text isn't sent anywhere.
- **Keyboard and mouse.** FlowType watches only its own shortcut keys (e.g. Ctrl+Alt) and, if you turn it on, one mouse button, to know when to listen. It does not record or store what you type.

## Sent over the internet (only with these features, each can be switched off)
| Feature | What is sent | To whom | How to turn it off |
|---|---|---|---|
| Grammar check, **Online** mode (off by default) | The text of each dictation | [LanguageTool](https://languagetool.org/legal/privacy) (`api.languagetool.org`) | Tray menu → **Grammar → Off** or **Offline** (Offline runs LanguageTool on your computer; it only downloads LanguageTool once from languagetool.org) |
| Meeting notes summary (only with an AI chosen) | The meeting transcript | The AI service you pick (Groq or Anthropic); nothing with Ollama or with no AI | Tray menu → **Command mode AI → Off** (you still get the transcript) |
| Update check (on by default) | A request for the latest version number, like opening a web page | GitHub (`api.github.com`) | Settings → Privacy → untick **Check GitHub for new versions** |
| Command mode (off until you choose an AI) | The instruction you speak and the text you selected | The AI service you pick: Groq, Anthropic (Claude), or none if you use Ollama, which runs on your computer | Tray menu → **Command mode AI → Off** |
| First start | A one-time download of the speech model | Hugging Face (download only, nothing about you is sent) | n/a |

FlowType has no accounts, no analytics, no telemetry and no ads. The FlowType project does not run any server and never receives your data.

## Contact
Questions: open an issue at https://github.com/soumyaswarrup/FlowType/issues
