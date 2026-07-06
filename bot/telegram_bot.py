"""Telegram bot front-end. Long polling means you can run this on your
laptop with zero hosting/webhook setup - fine for a prototype.
"""
import sys
import os
import logging
import random
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TELEGRAM_BOT_TOKEN, SMTP_EMAIL, SMTP_PASSWORD
from agent.agent_executor import ask
from tools.hr_tools import db_execute

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_employee_id_for_telegram_user(telegram_id: str):
    rows = db_execute("SELECT id, name FROM employees WHERE telegram_id = ?", (str(telegram_id),))
    return rows[0] if rows else None  # (id, name) or None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi, I'm your HR assistant.\n\n"
        "To get started, please register with your work email using:\n"
        "/register <your_email>\n\n"
        "Example:\n"
        "/register asha.rao@company.com"
    )


async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /register <your_email>")
        return
    
    email = context.args[0].strip().lower()
    telegram_id = str(update.effective_user.id)

    # 1. Lookup if employee exists with that email
    rows = db_execute("SELECT id, name FROM employees WHERE email = ?", (email,))
    if not rows:
        await update.message.reply_text(f"No registered employee found with email '{email}'. Please contact HR.")
        return
    
    employee_id, employee_name = rows[0]

    # 2. Generate random 6-digit OTP
    otp = f"{random.randint(100000, 999999)}"

    # 3. Store OTP in database
    db_execute("DELETE FROM pending_otps WHERE email = ?", (email,))
    db_execute(
        "INSERT INTO pending_otps (email, otp, created_at) VALUES (?, ?, ?)",
        (email, otp, datetime.now().isoformat())
    )

    # 4. Send OTP via Gmail SMTP if configured
    email_sent = False
    if SMTP_EMAIL and SMTP_PASSWORD:
        try:
            msg = MIMEMultipart()
            msg["From"] = f"HR Assistant <{SMTP_EMAIL}>"
            msg["To"] = email
            msg["Subject"] = "Your HR Bot Verification Code"
            
            body = f"Hi {employee_name},\n\nYour verification code for the HR Telegram Bot is: {otp}\n\nUse this code to verify your profile by sending `/verify {otp}` back to the bot."
            msg.attach(MIMEText(body, "plain"))
            
            # Connect and send via Gmail SMTP
            server = smtplib.SMTP("smtp.gmail.com", 587)
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, email, msg.as_string())
            server.quit()
            
            email_sent = True
        except Exception as e:
            logger.exception("Failed to send email via Gmail SMTP")

    # 5. Console fallback logging (essential for testing free tier)
    logger.info(f"\n========================================\n[OTP DEBUG] OTP for {email} ({employee_name}): {otp}\n========================================\n")

    if email_sent:
        await update.message.reply_text(
            f"Hi {employee_name}, I sent a 6-digit verification code to your email '{email}'.\n\n"
            "Please reply with:\n"
            f"/verify {otp}" if not email_sent else "/verify <code>"
        )
    else:
        await update.message.reply_text(
            f"Hi {employee_name}, I generated a verification code.\n\n"
            "*(Resend API sending skipped or failed. Look at your server terminal logs for the code!)*\n\n"
            "Please reply with:\n"
            "/verify <code>"
        )


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /verify <code>")
        return
    
    code = context.args[0].strip()
    telegram_id = str(update.effective_user.id)

    # Check if OTP matches
    rows = db_execute("SELECT email FROM pending_otps WHERE otp = ?", (code,))
    if not rows:
        await update.message.reply_text("Invalid or expired verification code. Please request a new code using /register <email>.")
        return
    
    email = rows[0][0]

    # Get employee details
    emp_rows = db_execute("SELECT id, name FROM employees WHERE email = ?", (email,))
    if not emp_rows:
        await update.message.reply_text("Employee details not found.")
        return
    
    employee_id, employee_name = emp_rows[0]

    # Map Telegram ID to Employee and clean up OTP
    db_execute("UPDATE employees SET telegram_id = ? WHERE email = ?", (telegram_id, email))
    db_execute("DELETE FROM pending_otps WHERE email = ?", (email,))

    await update.message.reply_text(
        f"Registration complete! Welcome {employee_name} (ID: {employee_id}). You can now ask me HR questions."
    )


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge click immediately to stop loading spinner
    
    data = query.data
    telegram_id = str(update.effective_user.id)
    
    # 1. Verify user clicking is a registered employee/manager
    manager_rows = db_execute("SELECT id, name FROM employees WHERE telegram_id = ?", (telegram_id,))
    if not manager_rows:
        await query.message.reply_text("You are not registered in the system. Cannot process approval.")
        return
    manager_id, manager_name = manager_rows[0]
    
    if not (data.startswith("approve_leave_") or data.startswith("reject_leave_")):
        return
    
    is_approve = data.startswith("approve_leave_")
    request_id = int(data.split("_")[-1])
    
    # 2. Fetch leave request details
    req_rows = db_execute(
        "SELECT employee_id, leave_type, start_date, end_date, days, status FROM leave_requests WHERE id = ?",
        (request_id,)
    )
    if not req_rows:
        await query.edit_message_text(text="Error: Leave request not found in database.")
        return
    
    employee_id, leave_type, start_date, end_date, days, current_status = req_rows[0]
    
    if current_status != "pending_manager_approval":
        status_label = "approved" if current_status == "approved" else "rejected"
        await query.edit_message_text(text=f"This request has already been processed (Current Status: {status_label.title()}).")
        return
    
    # 3. Update status in database
    new_status = "approved" if is_approve else "rejected"
    
    # Deduct balance if approved
    if is_approve:
        bal_rows = db_execute(
            "SELECT balance FROM leave_balances WHERE employee_id = ? AND leave_type = ?",
            (employee_id, leave_type)
        )
        if bal_rows:
            current_balance = bal_rows[0][0]
            new_balance = max(0.0, current_balance - days)
            db_execute(
                "UPDATE leave_balances SET balance = ? WHERE employee_id = ? AND leave_type = ?",
                (new_balance, employee_id, leave_type)
            )
            
    db_execute("UPDATE leave_requests SET status = ? WHERE id = ?", (new_status, request_id))
    
    # 4. Fetch employee details to notify them
    emp_rows = db_execute("SELECT telegram_id, name FROM employees WHERE id = ?", (employee_id,))
    employee_name = emp_rows[0][1] if emp_rows else "Employee"
    
    status_emoji = "✅ Approved" if is_approve else "❌ Rejected"
    
    # Update manager's message to show action taken
    await query.edit_message_text(
        text=f"📋 *Leave Request Processed*\n\n"
             f"👤 *Employee:* {employee_name}\n"
             f"🌴 *Type:* {leave_type.replace('_', ' ').title()}\n"
             f"📅 *Dates:* {start_date} to {end_date} ({days} day(s))\n\n"
             f"Status: {status_emoji} (by {manager_name})"
    )
    
    # 5. Notify employee if registered on Telegram
    if emp_rows and emp_rows[0][0]:
        emp_telegram_id = emp_rows[0][0]
        
        notify_text = (
            f"🔔 *Leave Request Update*\n\n"
            f"Your request for *{days} day(s)* of *{leave_type.replace('_', ' ').title()}* "
            f"from *{start_date} to {end_date}* has been *{new_status.upper()}* by manager {manager_name}."
        )
        
        try:
            await context.bot.send_message(chat_id=emp_telegram_id, text=notify_text, parse_mode="Markdown")
        except Exception as e:
            logger.exception(f"Failed to send update notification to employee {employee_name}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    employee = _get_employee_id_for_telegram_user(telegram_id)
    if employee is None:
        await update.message.reply_text("You're not registered yet. Please send /register <your_email> first.")
        return

    employee_id, _name = employee
    user_message = update.message.text

    try:
        reply = ask(employee_id, user_message)
    except Exception as e:
        logger.exception("Agent error")
        reply = "Sorry, something went wrong on my end. Please try again in a moment."

    await update.message.reply_text(reply)


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set - create a bot with @BotFather first.")

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting (long polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
