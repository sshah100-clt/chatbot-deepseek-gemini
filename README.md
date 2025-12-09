# Virtual Agent

Lightweight Django portal for chatting with multiple LLM providers and capturing conversation analytics.

## Simple guide (non-technical)
- Go to https://baseline.pythonanywhere.com/ in your browser.
- Enter a profile name (any unique name works) and pick a model, then click **Enter**.
- Type messages in the chat box and press **Send**; responses appear in the chat history.
- To view analytics , visit **Admin dashboard** and enter the admin access code; on the hosted site use `admin-secret`.


## Features
- Profile-based login with per-provider chat sessions and preserved context history.
- Switchable providers (DeepSeek or Gemini) with configurable system prompts and default provider.
- Conversation turns, token counts, latency, and model metadata persisted to SQLite for later review.
- Admin dashboard for inspecting profiles, sessions, and recent turns with basic filtering.
- Simple web UI built with Django templates; no external frontend build step required.

## Hosted demo
- Live instance: https://baseline.pythonanywhere.com/
- Login with any profile name; choose DeepSeek or Gemini.
- Admin dashboard: https://baseline.pythonanywhere.com/admin-dashboard/
- Admin access code on the hosted demo: `admin-secret` (enter this when prompted to view monitoring).
- To change the code for your own deployment, set `PORTAL_ADMIN_TOKEN` in `.env` 

## Quick start (local)
1) Ensure Python 3.10+ is installed.
2) Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\\Scripts\\activate
   ```
3) Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4) Create a `.env` file in the project root (see configuration below).
5) Apply database migrations:
   ```bash
   python manage.py migrate
   ```
6) Run the development server:
   ```bash
   python manage.py runserver
   ```
7) Open http://127.0.0.1:8000/ to log in and start chatting.

## Configuration
Environment variables are loaded from `.env` by `python-dotenv`. Common settings:

```env
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=True

# Model providers
DEFAULT_MODEL_PROVIDER=deepseek      # deepseek or gemini
DEEPSEEK_API_KEY=your_deepseek_key
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
DEEPSEEK_SYSTEM_PROMPT=You are a helpful assistant.

GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-2.5-flash
GEMINI_API_BASE=https://generativelanguage.googleapis.com/v1beta
GEMINI_SYSTEM_PROMPT=You are a helpful assistant.

# Admin dashboard
PORTAL_ADMIN_TOKEN=admin-secret
```

Notes:
- Set `PORTAL_ADMIN_TOKEN` to require an access code for the admin dashboard; leave blank to disable the requirement.
- The SQLite database at `db.sqlite3` stores profiles, sessions, and turns. Back up or replace it as needed per environment.
- Production deployments should set `DJANGO_DEBUG=False`, change `DJANGO_SECRET_KEY`, and adjust allowed hosts and HTTPS settings as appropriate.

## Usage
- Login: choose a profile name (identifier) and model provider, optionally supply a display name; enter the admin token to access monitoring.
- Chat: prompts and replies are sent to the selected provider and stored with token/latency metadata; context is preserved per profile and provider.
- Admin dashboard: `/admin-dashboard/` lists profiles, sessions, and recent turns with filters for profile and session IDs. On the hosted instance use https://baseline.pythonanywhere.com/admin-dashboard/ (requires token if enabled).


## Development tips
- Requirements are minimal (`Django`, `requests`, `python-dotenv`) and no frontend build is needed.
- If you rotate API keys or change providers, restart the server to pick up new environment variables.
