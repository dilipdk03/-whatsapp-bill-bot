# WhatsApp Bill → Excel Bot — Setup Guide

## What it does
Send any bill/receipt photo on WhatsApp → Bot extracts all data using Claude Vision → Sends you back a formatted Excel file.

---

## Prerequisites
- Python 3.9+
- A free Twilio account → https://twilio.com
- An Anthropic API key → https://console.anthropic.com
- ngrok (for local testing) → https://ngrok.com

---

## Step 1 — Install dependencies

```bash
cd whatsapp-bill-bot
pip install -r requirements.txt
```

---

## Step 2 — Get your API keys

### Anthropic (Claude)
1. Go to https://console.anthropic.com
2. API Keys → Create Key
3. Copy it into `.env` as `ANTHROPIC_API_KEY`

### Twilio WhatsApp Sandbox
1. Sign up at https://twilio.com (free)
2. Go to: Messaging → Try it out → Send a WhatsApp message
3. You'll see a sandbox number like `+14155238886`
4. Copy your Account SID and Auth Token from the dashboard
5. To activate the sandbox: WhatsApp your sandbox number with the join code shown (e.g. "join bright-mountain")

---

## Step 3 — Configure .env

```bash
cp .env.example .env
# Edit .env and fill in all four values
```

---

## Step 4 — Start ngrok (public URL for your local server)

```bash
# In a new terminal:
ngrok http 5000
```

Copy the `https://...ngrok.io` URL and paste it as `PUBLIC_URL` in your `.env`.

---

## Step 5 — Run the bot

```bash
python app.py
```

You should see:
```
* Running on http://127.0.0.1:5000
```

---

## Step 6 — Connect Twilio to your webhook

1. Twilio Console → Messaging → Settings → WhatsApp Sandbox Settings
2. Set **"When a message comes in"** to:
   ```
   https://your-ngrok-url.ngrok.io/webhook
   ```
   Method: `POST`
3. Save.

---

## Step 7 — Test it!

1. Open WhatsApp
2. Send any bill/receipt photo to your Twilio sandbox number
3. Bot replies with "Extracting data..."
4. In ~10 seconds you'll receive a summary message + the Excel file

---

## Flow diagram

```
You (WhatsApp)
    │  📸 bill photo
    ▼
Twilio Sandbox
    │  POST /webhook
    ▼
Flask Server (app.py)
    │  1. Downloads image from Twilio
    │  2. Sends to Claude Vision API
    │  3. Parses JSON response
    │  4. Creates Excel with openpyxl
    │  5. Serves file at /files/<name>
    │  6. Sends file URL back via Twilio
    ▼
Twilio Sandbox
    │  📎 Excel file
    ▼
You (WhatsApp)
```

---

## Deploying to production (after testing)

Instead of ngrok, deploy the Flask app to any cloud:

| Platform | Command |
|----------|---------|
| **Railway** | `railway up` (free tier available) |
| **Render** | Connect GitHub repo, deploy as Web Service |
| **AWS EC2** | `gunicorn app:app -b 0.0.0.0:5000` |

Update `PUBLIC_URL` in your `.env` to the production domain.
Also switch from Twilio Sandbox to a real WhatsApp Business number for production.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bot doesn't respond | Check ngrok is running and webhook URL is correct in Twilio |
| "Could not download image" | Twilio credentials may be wrong in .env |
| Excel not sending | Make sure PUBLIC_URL has no trailing slash |
| Claude error | Check ANTHROPIC_API_KEY is valid and has credits |

---

## Project structure

```
whatsapp-bill-bot/
├── app.py               ← Main Flask server (all logic here)
├── requirements.txt     ← Python dependencies
├── .env.example         ← Copy to .env and fill in values
├── .env                 ← Your actual secrets (never commit this!)
├── generated_files/     ← Excel files stored here temporarily
└── README.md            ← This file
```
