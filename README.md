# Mem0 Memory-First Reminder Bot (Slack)

## Requirements
- Python 3.10+
- Mem0 API credentials
- Anthropic API key
- (Optional) Supabase project for production storage
- (Optional) Slack app for integration

## Quickstart (local)
```bash
cd agent-backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment
Create `agent-backend/.env` with:
```
ANTHROPIC_API_KEY=...
MEM0_API_KEY=...
MEM0_ORG_ID=...
MEM0_PROJECT_ID=...
```

Optional (production DB + Slack):
```
SUPABASE_URL=...
SUPABASE_KEY=...
SLACK_BOT_TOKEN=...
SLACK_SIGNING_SECRET=...
ARCHIVE_CRON_TOKEN=...
```

## Run the API
```bash
cd agent-backend
uvicorn main:app --reload --port 8000
```
Open `http://localhost:8000` for the UI.

## Local Slack testing (ngrok)
Slack requires a public HTTPS URL. For local dev:
```bash
ngrok http 8000
```
Use the generated `https://...ngrok.io` base URL for:
- `https://YOUR_NGROK/slack/events`
- `https://YOUR_NGROK/slack/commands`
- `https://YOUR_NGROK/slack/interactions`

## Hosting (Render example)
Use any hosted service with HTTPS (Render, Fly, Railway, etc). Example for Render:
1) Create a new Web Service from this repo  
2) Set Root Directory: `agent-backend`  
3) Build Command: `pip install -r requirements.txt`  
4) Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`  
5) Add env vars from `.env` in Render’s dashboard  
6) Use the Render URL as your Slack Request URL base

## Slack integration (optional)
1) Create a Slack app at https://api.slack.com/apps  
2) **OAuth & Permissions**  
   - Add bot scopes: `chat:write`, `commands`, `im:history`  
   - Install the app to your workspace  
   - Copy the Bot User OAuth Token into `SLACK_BOT_TOKEN`
3) **Basic Information**  
   - Copy the Signing Secret into `SLACK_SIGNING_SECRET`
4) **Event Subscriptions**  
   - Enable events  
   - Request URL: `https://YOUR_DOMAIN/slack/events`  
   - Subscribe to bot events: `message.im`
5) **Slash Commands**  
   - Create a command, set Request URL: `https://YOUR_DOMAIN/slack/commands`
6) **Interactivity & Shortcuts**  
   - Enable Interactivity  
   - Request URL: `https://YOUR_DOMAIN/slack/interactions`
7) Update `agent-backend/.env` and restart the API:
```
SLACK_BOT_TOKEN=...
SLACK_SIGNING_SECRET=...
```

## Cron archiving (optional)
`POST /cron/archive_overdue` archives overdue reminders.  
Use a scheduler to call it:
```bash
curl -s -X POST \
  -H "x-cron-token: YOUR_SECRET_TOKEN" \
  http://localhost:8000/cron/archive_overdue
```
On hosted platforms, use a cron job/ scheduler to call the hosted URL.

## Mem0 setup (optional)
```bash
cd agent-backend
python set_mem0_instructions.py
```
