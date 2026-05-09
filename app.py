"""
WhatsApp Bill → Excel Bot (using Groq - FREE)
----------------------------------------------
Flow:
  1. User sends a bill/receipt image on WhatsApp
  2. Twilio forwards it to this Flask webhook
  3. We download the image and send it to Groq Vision API (FREE)
  4. Groq extracts structured JSON data
  5. We build a formatted Excel file with openpyxl
  6. We host the file on this server and send the public URL back via WhatsApp
"""

import os
import uuid
import json
import base64
import threading
import requests
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from flask import Flask, request, send_from_directory
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
GROQ_API_KEY           = os.getenv("GROQ_API_KEY")
TWILIO_ACCOUNT_SID     = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN      = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")  # whatsapp:+14155238886
PUBLIC_URL             = os.getenv("PUBLIC_URL")              # https://your-ngrok-url.ngrok-free.app

FILES_DIR = "generated_files"
os.makedirs(FILES_DIR, exist_ok=True)

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ── Prompt ───────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a bill and expense data extractor. Extract ALL data from the bill/receipt image and return ONLY a valid JSON object — no markdown, no backticks, no explanation whatsoever.

Return exactly this structure:
{
  "vendor": "store or restaurant name",
  "date": "date in YYYY-MM-DD format if possible",
  "bill_number": "invoice or receipt number or null",
  "category": "Food / Travel / Medical / Utilities / Shopping / etc.",
  "items": [
    { "description": "item name", "quantity": 1, "unit_price": 0.00, "total": 0.00 }
  ],
  "subtotal": 0.00,
  "tax": 0.00,
  "discount": 0.00,
  "tip": 0.00,
  "total": 0.00,
  "payment_method": "Cash / Card / UPI / etc. or null",
  "currency": "INR or USD etc.",
  "notes": "any other info or null"
}

Use null for missing fields. Return pure JSON only."""


# ── Step 1: Receive WhatsApp webhook ─────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    num_media   = int(request.form.get("NumMedia", 0))
    from_number = request.form.get("From")

    if num_media == 0:
        resp = MessagingResponse()
        resp.message(
            "👋 Hi! I'm your *Bill to Excel* bot.\n\n"
            "📸 Send me a photo of any:\n"
            "• Restaurant or shop bill\n"
            "• Invoice or receipt\n"
            "• Expense document\n\n"
            "I'll extract all the data and send you back an Excel file! 📊"
        )
        return str(resp)

    media_url  = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0", "image/jpeg")

    print(f"[DEBUG] Received image from {from_number}")
    print(f"[DEBUG] Media URL: {media_url}")

    send_whatsapp_message(from_number, "⏳ Got your bill! Extracting data... please wait a moment.")

    thread = threading.Thread(
        target=process_bill,
        args=(from_number, media_url, media_type)
    )
    thread.start()

    return "", 200


# ── Step 2: Download image → Groq → Excel → Reply ────────────────────────────
def process_bill(to_number, media_url, media_type):
    try:
        print(f"[DEBUG] Downloading image...")
        image_b64 = download_twilio_image(media_url)
        if not image_b64:
            send_whatsapp_message(to_number, "❌ Could not download the image. Please try again.")
            return

        print(f"[DEBUG] Calling Groq API...")
        bill_data = extract_bill_with_groq(image_b64, media_type)
        if not bill_data:
            send_whatsapp_message(to_number, "❌ Could not read the bill. Make sure the image is clear and try again.")
            return

        print(f"[DEBUG] Building Excel...")
        filename = f"bill_{uuid.uuid4().hex[:8]}.xlsx"
        filepath = os.path.join(FILES_DIR, filename)
        create_excel(bill_data, filepath)

        file_url = f"{PUBLIC_URL}/files/{filename}"
        print(f"[DEBUG] File URL: {file_url}")

        summary = build_summary_message(bill_data)
        send_whatsapp_message(to_number, summary)
        send_whatsapp_media(to_number, file_url, filename)

    except Exception as e:
        print(f"[ERROR] process_bill failed: {e}")
        send_whatsapp_message(to_number, "❌ Something went wrong. Please try again.")


# ── Step 3: Download image from Twilio ───────────────────────────────────────
def download_twilio_image(media_url):
    try:
        response = requests.get(
            media_url,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=15
        )
        response.raise_for_status()
        print(f"[DEBUG] Image downloaded, size: {len(response.content)} bytes")
        return base64.b64encode(response.content).decode("utf-8")
    except Exception as e:
        print(f"[ERROR] Image download failed: {e}")
        return None


# ── Step 4: Groq Vision API call (FREE) ──────────────────────────────────────
def extract_bill_with_groq(image_b64, media_type):
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "max_tokens": 1024,
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{image_b64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": "Extract all bill/expense data from this image as JSON."
                            }
                        ]
                    }
                ]
            },
            timeout=30
        )
        response.raise_for_status()
        raw_text = response.json()["choices"][0]["message"]["content"]
        print(f"[DEBUG] Groq response: {raw_text[:200]}")
        clean = raw_text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        print(f"[ERROR] Groq API failed: {e}")
        return None


# ── Step 5: Build formatted Excel ────────────────────────────────────────────
def create_excel(data, filepath):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bill Data"

    GREEN_DARK = "1A5276"
    GREEN_MID  = "D5F5E3"
    GRAY_LIGHT = "F2F3F4"
    WHITE      = "FFFFFF"
    DARK_TEXT  = "1C2833"

    def header_font(): return Font(bold=True, color="FFFFFF", size=11)
    def section_font(): return Font(bold=True, color=DARK_TEXT, size=10)
    def label_font(): return Font(color="5D6D7E", size=10)
    def value_font(): return Font(color=DARK_TEXT, size=10)
    def total_font(): return Font(bold=True, color=DARK_TEXT, size=11)
    def fill(hex_color): return PatternFill("solid", fgColor=hex_color)
    def thin_border():
        s = Side(style="thin", color="D5D8DC")
        return Border(left=s, right=s, top=s, bottom=s)
    def center(): return Alignment(horizontal="center", vertical="center")
    def left(): return Alignment(horizontal="left", vertical="center")
    def right(): return Alignment(horizontal="right", vertical="center")

    row = 1

    # Title
    ws.merge_cells(f"A{row}:F{row}")
    ws[f"A{row}"] = "Bill / Expense Report"
    ws[f"A{row}"].font = Font(bold=True, color="FFFFFF", size=13)
    ws[f"A{row}"].fill = fill(GREEN_DARK)
    ws[f"A{row}"].alignment = center()
    ws.row_dimensions[row].height = 28
    row += 1

    # Bill Info
    info_fields = [
        ("Vendor",         data.get("vendor")),
        ("Date",           data.get("date")),
        ("Bill Number",    data.get("bill_number")),
        ("Category",       data.get("category")),
        ("Payment Method", data.get("payment_method")),
        ("Currency",       data.get("currency")),
    ]

    ws.merge_cells(f"A{row}:F{row}")
    ws[f"A{row}"] = "Bill Information"
    ws[f"A{row}"].font = section_font()
    ws[f"A{row}"].fill = fill(GREEN_MID)
    ws[f"A{row}"].alignment = left()
    ws.row_dimensions[row].height = 20
    row += 1

    for label, value in info_fields:
        if value is None:
            continue
        ws[f"A{row}"] = label
        ws[f"A{row}"].font = label_font()
        ws[f"A{row}"].alignment = left()
        ws.merge_cells(f"B{row}:F{row}")
        ws[f"B{row}"] = str(value)
        ws[f"B{row}"].font = value_font()
        ws[f"B{row}"].alignment = left()
        bg = WHITE if row % 2 == 0 else GRAY_LIGHT
        for col in ["A", "B", "C", "D", "E", "F"]:
            ws[f"{col}{row}"].fill = fill(bg)
            ws[f"{col}{row}"].border = thin_border()
        row += 1

    row += 1

    # Items
    ws.merge_cells(f"A{row}:F{row}")
    ws[f"A{row}"] = "Line Items"
    ws[f"A{row}"].font = section_font()
    ws[f"A{row}"].fill = fill(GREEN_MID)
    ws[f"A{row}"].alignment = left()
    ws.row_dimensions[row].height = 20
    row += 1

    col_headers = ["#", "Description", "Quantity", "Unit Price", "Total", ""]
    col_widths   = [5,   30,            12,          14,           14,      5]
    for col_idx, (h, w) in enumerate(zip(col_headers, col_widths), start=1):
        cell = ws.cell(row=row, column=col_idx, value=h)
        cell.font = header_font()
        cell.fill = fill(GREEN_DARK)
        cell.alignment = center()
        cell.border = thin_border()
        ws.column_dimensions[get_column_letter(col_idx)].width = w
    ws.row_dimensions[row].height = 22
    row += 1

    items = data.get("items") or []
    curr  = data.get("currency", "")
    for i, item in enumerate(items, start=1):
        bg = WHITE if i % 2 == 0 else GRAY_LIGHT
        values = [
            i,
            item.get("description", ""),
            item.get("quantity", ""),
            f"{curr} {item.get('unit_price', '')}" if item.get("unit_price") is not None else "",
            f"{curr} {item.get('total', '')}"       if item.get("total") is not None else "",
            ""
        ]
        for col_idx, val in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col_idx, value=val)
            cell.font      = value_font()
            cell.fill      = fill(bg)
            cell.border    = thin_border()
            cell.alignment = right() if col_idx >= 3 else left()
        row += 1

    row += 1

    # Summary
    ws.merge_cells(f"A{row}:F{row}")
    ws[f"A{row}"] = "Summary"
    ws[f"A{row}"].font = section_font()
    ws[f"A{row}"].fill = fill(GREEN_MID)
    ws[f"A{row}"].alignment = left()
    row += 1

    totals = [
        ("Subtotal", data.get("subtotal")),
        ("Tax",      data.get("tax")),
        ("Discount", data.get("discount")),
        ("Tip",      data.get("tip")),
    ]
    for label, value in totals:
        if value is None:
            continue
        ws.merge_cells(f"A{row}:D{row}")
        ws[f"A{row}"] = label
        ws[f"A{row}"].font = label_font()
        ws[f"A{row}"].alignment = right()
        ws.merge_cells(f"E{row}:F{row}")
        ws[f"E{row}"] = f"{curr} {value}"
        ws[f"E{row}"].font = value_font()
        ws[f"E{row}"].alignment = right()
        bg = WHITE if row % 2 == 0 else GRAY_LIGHT
        for col in ["A", "B", "C", "D", "E", "F"]:
            ws[f"{col}{row}"].fill   = fill(bg)
            ws[f"{col}{row}"].border = thin_border()
        row += 1

    # Grand total
    ws.merge_cells(f"A{row}:D{row}")
    ws[f"A{row}"] = "TOTAL"
    ws[f"A{row}"].font = total_font()
    ws[f"A{row}"].fill = fill(GREEN_DARK)
    ws[f"A{row}"].alignment = right()
    ws.merge_cells(f"E{row}:F{row}")
    ws[f"E{row}"] = f"{curr} {data.get('total', '')}"
    ws[f"E{row}"].font = Font(bold=True, color="FFFFFF", size=12)
    ws[f"E{row}"].fill = fill(GREEN_DARK)
    ws[f"E{row}"].alignment = right()
    for col in ["A", "B", "C", "D", "E", "F"]:
        ws[f"{col}{row}"].border = thin_border()
    ws.row_dimensions[row].height = 24
    row += 1

    if data.get("notes"):
        row += 1
        ws.merge_cells(f"A{row}:F{row}")
        ws[f"A{row}"] = f"Notes: {data['notes']}"
        ws[f"A{row}"].font = label_font()
        ws[f"A{row}"].alignment = left()

    ws.freeze_panes = "A2"
    wb.save(filepath)
    print(f"[INFO] Excel saved: {filepath}")


# ── Step 6: Send WhatsApp messages ───────────────────────────────────────────
def send_whatsapp_message(to, body):
    twilio_client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=to,
        body=body
    )

def send_whatsapp_media(to, media_url, filename):
    twilio_client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=to,
        body=f"📎 *Your Excel file is ready!*\n\nDownload it here:\n{media_url}\n\nOpen the link and save the file."
    )

def build_summary_message(data):
    items = data.get("items") or []
    curr  = data.get("currency", "")
    total = data.get("total")
    lines = ["✅ *Bill extracted successfully!*\n"]
    if data.get("vendor"):   lines.append(f"🏪 *Vendor:* {data['vendor']}")
    if data.get("date"):     lines.append(f"📅 *Date:* {data['date']}")
    if data.get("category"): lines.append(f"🏷️ *Category:* {data['category']}")
    lines.append(f"🧾 *Items found:* {len(items)}")
    if total is not None:    lines.append(f"💰 *Total:* {curr} {total}")
    lines.append("\n📥 Sending your Excel file now...")
    return "\n".join(lines)


# ── Serve generated files ─────────────────────────────────────────────────────
@app.route("/files/<filename>")
def serve_file(filename):
    return send_from_directory(FILES_DIR, filename, as_attachment=True)

@app.route("/", methods=["GET"])
def health():
    return {"status": "running", "bot": "WhatsApp Bill → Excel (Groq)"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)