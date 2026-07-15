# ReqPilot operations guide

## Pre-workshop checklist

1. Start Ollama and confirm the configured model is installed.
2. Run `python -m scripts.diagnose --server` after starting ReqPilot.
3. Open `http://127.0.0.1:8765` in Chrome, Edge, or Safari.
4. For live mode, select the intended microphone and grant permission.
5. For a sensitive workshop, verify `.env` selects `ollama` and the header says
   local-only.

## Start and stop

On Windows, use `run_windows.bat`. On macOS, run `./run_mac.sh`. Both create a
virtual environment on first use, install from `wheelhouse/` when present,
check speech models, and start the localhost server.

Stop the server with Ctrl+C in its terminal. Finalized transcript and state are
already saved; reopening the app lists previous sessions.

## Transcript import

Choose **Import transcript**, paste text or select a TXT, VTT, or DOCX file,
then run the import. Imported files never construct the microphone or ASR
pipeline. Review the canvas before generating the BRD and story set.

## Back up and restore

Copy the complete `data/` folder while ReqPilot is stopped. To move storage,
set `REQPILOT_DATA_DIR` in `.env`, copy existing session folders to the new
location, start ReqPilot, and confirm the session list before removing the old
copy.

## Jira

Set `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, and `JIRA_PROJECT_KEY` in
`.env`. Restart ReqPilot, confirm Jira is shown as configured, and always use
preview first. Sync is idempotent for the session because returned issue keys
are persisted in `delivery.json`.

## Troubleshooting

- **Microphone denied:** allow microphone access for `127.0.0.1` in browser site
  settings, reload, and start again.
- **No live text:** confirm the recording indicator moves and run diagnostics
  to verify both speech model folders.
- **Ollama unavailable:** run `ollama list`, start the Ollama service, and check
  `OLLAMA_BASE_URL` and `OLLAMA_MODEL`.
- **Cloud provider error:** verify the provider key is set only in `.env` and
  that the machine is allowed to reach the provider.
- **Import rejected:** confirm the extension is TXT/VTT/DOCX and the file is
  below 10 MiB. Re-export damaged DOCX files from Word.
- **Jira rejected:** check project key, issue permissions, and that Epic and
  Story issue types are available in the target project.

## Offline transfer

Build the archive on the same operating system and architecture as the target:

```powershell
python -m scripts.build_offline_bundle
```

Use `scripts.bundle_parts` to split large archives for transfer. The manifest,
every part, and the reassembled ZIP are protected by SHA-256 checksums. On the
destination, extract the archive and run the platform launcher; package and
model downloads are not required when the wheelhouse and models are present.
