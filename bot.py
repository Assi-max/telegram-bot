import gspread
import asyncio
import random
import string
import os
import pandas as pd
from datetime import datetime
import tempfile
from google.oauth2.service_account import Credentials

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

import json


TOKEN = os.environ.get("BOT_TOKEN")

ADMIN_IDS = [5740687171]

CHANNEL_URL = "https://t.me/millennium_eye_store"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))

creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=SCOPES
)

client = gspread.authorize(creds)
spreadsheet = client.open("MES Orders Database")
sheet = spreadsheet.worksheet("Orders")
archive_sheet = spreadsheet.worksheet("Archive")
logs_sheet = spreadsheet.worksheet("Logs")

# ترتيب الأعمدة في ورقة Orders
# OrderID | TrackingCode | CustomerName | Status | TelegramID | PhoneNumber | CityAndBranch | OrderWithPrice | TotalPrice | TypeOfCards | CreatedDate | Notes

# ترتيب الأعمدة في ورقة Archive
# OrderID | TrackingCode | CustomerName | Status | TelegramID | PhoneNumber | CityAndBranch | OrderWithPrice | TotalPrice | TypeOfCards | CreatedDate | Notes | ArchivedDate

# ترتيب الأعمدة في ورقة Logs
# OrderID | TrackingCode | Action | ByWhom | Date

# ===================== حالات المحادثة =====================
(
    MAIN_MENU,
    TRACK_WAIT_CODE,
    ADMIN_MENU,
    ASK_NAME,
    ASK_PHONE,
    ASK_CITY,
    ASK_ORDER,
    ASK_TOTAL,
    ASK_CARD_TYPE,
    ASK_NOTES,
    ASK_DATE,
    CONFIRM_ORDER,
    EDIT_ASK_CODE,
    EDIT_CHOOSE_FIELD,
    EDIT_TEXT_INPUT,
    SEARCH_CHOOSE_TYPE,
    SEARCH_WAIT_INPUT,
    DELETE_WAIT_CODE,
    DELETE_CONFIRM,
    EXPORT_CHOOSE,
) = range(20)


VALID_STATUSES = [
    "Received",
    "Designing",
    "WaitingPrint",
    "Printing",
    "Ready",
    "Delivered"
]

STATUS_MAP = {
    "Received": "تم استلام الطلب ✅",
    "Designing": "قيد التصميم 🎨",
    "WaitingPrint": "بانتظار الطباعة ⏳",
    "Printing": "قيد الطباعة 🖨️",
    "Ready": "جاهز للاستلام 📦",
    "Delivered": "تم التسليم 🎉"
}

CARD_TYPE_OPTIONS = ["انكليزي", "عربي", "انمي ستايل", "لا ينطبق"]


# ===================== دوال مساعدة عامة =====================

def is_admin(user_id):
    return user_id in ADMIN_IDS


def generate_tracking_code():
    """توليد رمز تتبع فريد مكون من حروف وأرقام"""
    return "MES-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def generate_order_id():
    """توليد معرف طلب تسلسلي"""
    try:
        all_orders = sheet.get_all_records()
        if not all_orders:
            return "ORD-0001"
        last_id = all_orders[-1].get("OrderID", "ORD-0000")
        num = int(last_id.split("-")[1]) + 1
        return f"ORD-{num:04d}"
    except:
        return "ORD-" + "".join(random.choices(string.digits, k=4))


def get_actor_name(update: Update) -> str:
    """ترجع اسم/معرف الشخص الذي قام بالعملية لتسجيله في Logs"""
    user = update.effective_user
    if user.username:
        return f"@{user.username}"
    return f"{user.full_name} ({user.id})"


def log_action(order_id: str, tracking_code: str, action: str, by_whom: str):
    """تسجيل عملية في ورقة Logs"""
    try:
        row = [
            order_id,
            tracking_code,
            action,
            by_whom,
            datetime.now().strftime("%d-%m-%Y %H:%M"),
        ]
        logs_sheet.append_row(row)
    except Exception as e:
        print(f"خطأ في تسجيل Log: {e}")


def archive_order(order: dict):
    """نقل طلبية كاملة إلى ورقة Archive مع تاريخ الأرشفة"""
    row = [
        order.get("OrderID", ""),
        order.get("TrackingCode", ""),
        order.get("CustomerName", ""),
        order.get("Status", ""),
        order.get("TelegramID", ""),
        order.get("PhoneNumber", ""),
        order.get("CityAndBranch", ""),
        order.get("OrderWithPrice", ""),
        order.get("TotalPrice", ""),
        order.get("TypeOfCards", ""),
        order.get("CreatedDate", ""),
        order.get("Notes", ""),
        datetime.now().strftime("%d-%m-%Y %H:%M"),
    ]
    archive_sheet.append_row(row)


def format_order_summary(data: dict) -> str:
    """تنسيق ملخص طلبية جديدة قيد الإدخال"""
    card_type = data.get("card_type", "—")
    notes = data.get("notes", "—")

    return (
        f"📋 *ملخص الطلبية*\n\n"
        f"🔸 الاسم الثلاثي: {data['name']}\n"
        f"🔸 رقم الموبايل: {data['phone']}\n"
        f"🔸 المدينة/الفرع: {data['city']}\n"
        f"🔸 الطلبية والسعر:\n{data['order']}\n"
        f"🔸 السعر النهائي: {data['total']}\n"
        f"🔸 نوع البطاقات: {card_type}\n"
        f"🔸 الملاحظات: {notes}\n"
        f"🔸 تاريخ الطلبية: {data['date']}"
    )


def format_order_full(order: dict) -> str:
    """تنسيق طلبية كاملة من السجل (للعرض/البحث/الأرشيف)"""
    status = STATUS_MAP.get(order.get("Status", ""), order.get("Status", "—"))
    card_type = order.get("TypeOfCards", "") or "—"
    notes = order.get("Notes", "") or "—"
    phone = order.get("PhoneNumber", "") or "—"
    city = order.get("CityAndBranch", "") or "—"
    order_details = order.get("OrderWithPrice", "") or "—"
    total = order.get("TotalPrice", "") or "—"
    date = order.get("CreatedDate", "") or "—"
    name = order.get("CustomerName", "") or "—"

    return (
        f"🆔 معرف الطلب: `{order.get('OrderID', '')}`\n"
        f"🔑 رمز التتبع: `{order.get('TrackingCode', '')}`\n\n"
        f"👤 الاسم: {name}\n"
        f"📱 الموبايل: {phone}\n"
        f"🏙️ المدينة/الفرع: {city}\n"
        f"🧾 الطلبية والسعر:\n{order_details}\n"
        f"💰 السعر النهائي: {total}\n"
        f"🃏 نوع البطاقات: {card_type}\n"
        f"📋 الحالة: {status}\n"
        f"📅 تاريخ الطلبية: {date}\n"
        f"📝 الملاحظات: {notes}"
    )


# ===================== القوائم (Inline Keyboards) =====================

def main_menu_keyboard(user_id):
    rows = [[InlineKeyboardButton("🔍 استعلام عن طلب", callback_data="main_track")]]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("🛠️ وضع الأدمن", callback_data="main_admin")])
    rows.append([InlineKeyboardButton("📢 قناة المنتجات", url=CHANNEL_URL)])
    return InlineKeyboardMarkup(rows)


def admin_menu_keyboard():
    rows = [
        [InlineKeyboardButton("➕ إضافة طلبية", callback_data="admin_new")],
        [InlineKeyboardButton("✏️ تعديل طلبية", callback_data="admin_edit")],
        [InlineKeyboardButton("🔍 بحث عن طلبية", callback_data="admin_search")],
        [InlineKeyboardButton("🗑️ حذف/أرشفة طلبية", callback_data="admin_delete")],
        [InlineKeyboardButton("📋 عرض كل الطلبات", callback_data="admin_list")],
        [InlineKeyboardButton("📊 إحصائية الطلبات", callback_data="admin_stats")],
        [InlineKeyboardButton("📥 تحميل ملفات Excel", callback_data="admin_export")],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="main_back")],
    ]
    return InlineKeyboardMarkup(rows)


def export_choose_keyboard():
    rows = [
        [InlineKeyboardButton("📦 ملف Orders", callback_data="export_Orders")],
        [InlineKeyboardButton("🗄️ ملف Archive", callback_data="export_Archive")],
        [InlineKeyboardButton("📜 ملف Logs", callback_data="export_Logs")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="export_back")],
    ]
    return InlineKeyboardMarkup(rows)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text=None):
    user_id = update.effective_user.id
    if text is None:
        text = "👋 أهلاً بك في *نظام متابعة الطلبات*\n\nاختر من القائمة:"
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(user_id)
    )


async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text=None):
    if text is None:
        text = "🛠️ *لوحة تحكم الأدمن*\n\nاختر العملية المطلوبة:"
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode="Markdown",
        reply_markup=admin_menu_keyboard()
    )


# ===================== /start =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await show_main_menu(update, context)
    return MAIN_MENU


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data == "main_track":
        await query.edit_message_text(
            "🔍 *استعلام عن طلب*\n\nأرسل رمز التتبع الخاص بطلبك (مثال: MES-AB1234).",
            parse_mode="Markdown"
        )
        return TRACK_WAIT_CODE

    if data == "main_admin":
        if not is_admin(user_id):
            await query.edit_message_text("❌ ليس لديك صلاحية الوصول لوضع الأدمن.")
            await show_main_menu(update, context)
            return MAIN_MENU

        await query.edit_message_text(
            "🛠️ *لوحة تحكم الأدمن*\n\nاختر العملية المطلوبة:",
            parse_mode="Markdown",
            reply_markup=admin_menu_keyboard()
        )
        return ADMIN_MENU

    return MAIN_MENU


# ===================== استعلام الزبون عن طلب =====================

async def track_receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tracking_code = update.message.text.strip().upper()

    if len(tracking_code) < 4:
        await update.message.reply_text(
            "❓ أرسل رمز التتبع الخاص بطلبك.\n(مثال: MES-AB1234)"
        )
        return TRACK_WAIT_CODE

    orders = sheet.get_all_records()

    for index, order in enumerate(orders, start=2):
        if order.get("TrackingCode", "").upper() == tracking_code:

            telegram_id = str(update.effective_user.id)

            if not order.get("TelegramID"):
                sheet.update_cell(index, 5, telegram_id)

            status = STATUS_MAP.get(order["Status"], order["Status"])

            msg = (
                f"📦 *حالة الطلب*\n\n"
                f"🔑 رمز التتبع: `{tracking_code}`\n"
                f"👤 الاسم: {order['CustomerName']}\n"
                f"📋 الحالة الحالية: {status}\n\n"
                f"🔔 سيتم إشعارك تلقائياً عند أي تحديث."
            )

            await update.message.reply_text(msg, parse_mode="Markdown")
            await show_main_menu(update, context)
            return MAIN_MENU

    await update.message.reply_text(
        "❌ لم يتم العثور على طلب بهذا الرمز.\n\nتأكد من الرمز وأعد إرساله، أو اضغط /start للرجوع."
    )
    return TRACK_WAIT_CODE


# ===================== إضافة طلبية جديدة =====================

async def new_order_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update.effective_user.id):
        await query.edit_message_text("❌ ليس لديك صلاحية لإضافة طلبية.")
        await show_main_menu(update, context)
        return MAIN_MENU

    context.user_data.clear()
    await query.edit_message_text(
        "📝 *إضافة طلبية جديدة*\n\nأرسل /cancel في أي وقت للإلغاء والرجوع.\n\n"
        "🔸 الاسم الثلاثي للزبون؟",
        parse_mode="Markdown"
    )
    return ASK_NAME


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("🔸 رقم الموبايل؟")
    return ASK_PHONE


async def ask_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("🔸 المدينة والفرع؟")
    return ASK_CITY


async def ask_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["city"] = update.message.text.strip()
    await update.message.reply_text(
        "🔸 الطلبية والسعر؟\n"
        "(أدخل تفاصيل الطلبية مع سعر كل عنصر)"
    )
    return ASK_ORDER


async def ask_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order"] = update.message.text.strip()
    await update.message.reply_text("🔸 السعر النهائي الإجمالي؟\n(مثال: 18.9$)")
    return ASK_TOTAL


async def ask_card_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["total"] = update.message.text.strip()

    buttons = [[InlineKeyboardButton(ct, callback_data=f"newcard_{ct}")] for ct in CARD_TYPE_OPTIONS]
    await update.message.reply_text(
        "🔸 نوع البطاقات؟",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ASK_CARD_TYPE


async def ask_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    card_type = query.data.replace("newcard_", "")
    context.user_data["card_type"] = "" if card_type == "لا ينطبق" else card_type

    await query.edit_message_text(
        "🔸 ملاحظات؟\n(أرسل — إذا لا يوجد ملاحظات)"
    )
    return ASK_NOTES


async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = update.message.text.strip()
    context.user_data["notes"] = "" if notes == "—" else notes

    today = datetime.now().strftime("%d-%m-%Y")
    await update.message.reply_text(
        f"🔸 تاريخ الطلبية؟\n(أرسل — لاستخدام تاريخ اليوم: {today})"
    )
    return ASK_DATE


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_input = update.message.text.strip()
    if date_input == "—":
        context.user_data["date"] = datetime.now().strftime("%d-%m-%Y")
    else:
        context.user_data["date"] = date_input

    summary = format_order_summary(context.user_data)

    buttons = [[
        InlineKeyboardButton("✅ تأكيد وحفظ", callback_data="neworder_confirm"),
        InlineKeyboardButton("❌ إلغاء", callback_data="neworder_cancel"),
    ]]
    await update.message.reply_text(
        f"{summary}\n\nهل تريد حفظ هذه الطلبية؟",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return CONFIRM_ORDER


async def save_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "neworder_cancel":
        await query.edit_message_text("❌ تم إلغاء الطلبية.")
        context.user_data.clear()
        await show_admin_menu(update, context)
        return ADMIN_MENU

    data = context.user_data

    order_id = generate_order_id()
    tracking_code = generate_tracking_code()

    # OrderID | TrackingCode | CustomerName | Status | TelegramID | PhoneNumber | CityAndBranch | OrderWithPrice | TotalPrice | TypeOfCards | CreatedDate | Notes
    row = [
        order_id,
        tracking_code,
        data["name"],
        "Received",
        "",
        data["phone"],
        data["city"],
        data["order"],
        data["total"],
        data.get("card_type", ""),
        data["date"],
        data.get("notes", "")
    ]

    sheet.append_row(row)

    log_action(order_id, tracking_code, "إضافة طلبية جديدة", get_actor_name(update))

    summary = format_order_summary(data)
    confirmation_msg = (
        f"✅ *تم حفظ الطلبية بنجاح!*\n\n"
        f"{summary}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 معرف الطلب: `{order_id}`\n"
        f"🔑 رمز التتبع: `{tracking_code}`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 أرسل رمز التتبع للزبون ليتابع طلبه."
    )

    await query.edit_message_text(confirmation_msg, parse_mode="Markdown")

    context.user_data.clear()
    await show_admin_menu(update, context)
    return ADMIN_MENU


async def cancel_to_admin_or_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فالباك /cancel: يرجع للوحة الأدمن إذا كان أدمن، أو للقائمة الرئيسية"""
    context.user_data.clear()
    await update.message.reply_text("❌ تم إلغاء العملية والرجوع.")
    if is_admin(update.effective_user.id):
        await show_admin_menu(update, context)
        return ADMIN_MENU
    else:
        await show_main_menu(update, context)
        return MAIN_MENU


# ===================== تعديل طلبية =====================

# الحقول القابلة للتعديل: (اسم العرض، رقم العمود في الشيت)
EDITABLE_FIELDS = {
    "name":     ("👤 اسم الزبون",        3),
    "phone":    ("📱 رقم الموبايل",      6),
    "city":     ("🏙️ المدينة/الفرع",     7),
    "order":    ("🧾 الطلبية والسعر",    8),
    "total":    ("💰 السعر النهائي",     9),
    "cardtype": ("🃏 نوع البطاقات",      10),
    "status":   ("📋 حالة الطلب",        4),
    "date":     ("📅 تاريخ الطلبية",     11),
    "notes":    ("📝 الملاحظات",         12),
}


def build_fields_keyboard(edited_fields: dict):
    buttons = []
    for key, (label, _) in EDITABLE_FIELDS.items():
        text = label
        if key in edited_fields:
            text = f"✏️ {label} ✅"
        buttons.append([InlineKeyboardButton(text, callback_data=f"field_{key}")])

    buttons.append([
        InlineKeyboardButton("💾 حفظ التعديلات", callback_data="save_edit"),
        InlineKeyboardButton("❌ إلغاء", callback_data="cancel_edit"),
    ])
    return InlineKeyboardMarkup(buttons)


def build_status_keyboard():
    buttons = []
    for status in VALID_STATUSES:
        buttons.append([InlineKeyboardButton(STATUS_MAP[status], callback_data=f"value_status_{status}")])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_fields")])
    return InlineKeyboardMarkup(buttons)


def build_cardtype_keyboard():
    buttons = []
    for ct in CARD_TYPE_OPTIONS:
        buttons.append([InlineKeyboardButton(ct, callback_data=f"value_cardtype_{ct}")])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_fields")])
    return InlineKeyboardMarkup(buttons)


def format_edit_overview(order: dict, edited_fields: dict) -> str:
    def current(key, sheet_key):
        if key in edited_fields:
            value = edited_fields[key]
            return f"{value}  ✏️ (جديد)"
        value = order.get(sheet_key, "")
        return value if value not in ("", None) else "—"

    lines = [
        "🛠️ *تعديل الطلبية*",
        "",
        f"🆔 معرف الطلب: `{order.get('OrderID', '')}`",
        f"🔑 رمز التتبع: `{order.get('TrackingCode', '')}`",
        "",
        f"👤 الاسم: {current('name', 'CustomerName')}",
        f"📱 الموبايل: {current('phone', 'PhoneNumber')}",
        f"🏙️ المدينة/الفرع: {current('city', 'CityAndBranch')}",
        f"🧾 الطلبية والسعر: {current('order', 'OrderWithPrice')}",
        f"💰 السعر النهائي: {current('total', 'TotalPrice')}",
        f"🃏 نوع البطاقات: {current('cardtype', 'TypeOfCards')}",
        f"📋 الحالة: {current('status', 'Status')}",
        f"📅 التاريخ: {current('date', 'CreatedDate')}",
        f"📝 الملاحظات: {current('notes', 'Notes')}",
        "",
        "👇 اختر الحقل الذي تريد تعديله، أو احفظ التعديلات، أو ألغِ العملية."
    ]
    return "\n".join(lines)


async def edit_order_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update.effective_user.id):
        await query.edit_message_text("❌ ليس لديك صلاحية لتعديل الطلبيات.")
        await show_main_menu(update, context)
        return MAIN_MENU

    context.user_data.clear()
    await query.edit_message_text(
        "🛠️ *تعديل طلبية*\n\n"
        "أرسل رمز التتبع الخاص بالطلبية التي تريد تعديلها.\n"
        "أرسل /cancel للإلغاء في أي وقت.",
        parse_mode="Markdown"
    )
    return EDIT_ASK_CODE


async def edit_receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tracking_code = update.message.text.strip().upper()

    orders = sheet.get_all_records()

    for index, order in enumerate(orders, start=2):
        if order.get("TrackingCode", "").upper() == tracking_code:
            context.user_data["edit_row_index"] = index
            context.user_data["edit_order"] = order
            context.user_data["edit_fields"] = {}

            text = format_edit_overview(order, {})
            await update.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=build_fields_keyboard({})
            )
            return EDIT_CHOOSE_FIELD

    await update.message.reply_text(
        "❌ لم يتم العثور على طلبية بهذا الرمز.\nأعد إرسال الرمز الصحيح أو /cancel للإلغاء."
    )
    return EDIT_ASK_CODE


async def edit_choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    order = context.user_data.get("edit_order", {})
    edited_fields = context.user_data.get("edit_fields", {})

    if data == "cancel_edit":
        context.user_data.clear()
        await query.edit_message_text("❌ تم إلغاء عملية التعديل، لم يتم حفظ أي تغييرات.", parse_mode="Markdown")
        await show_admin_menu(update, context)
        return ADMIN_MENU

    if data == "save_edit":
        if not edited_fields:
            await query.answer("⚠️ لم تقم بتعديل أي حقل بعد.", show_alert=True)
            return EDIT_CHOOSE_FIELD

        row_index = context.user_data["edit_row_index"]

        for key, value in edited_fields.items():
            _, col = EDITABLE_FIELDS[key]
            sheet.update_cell(row_index, col, value)

        summary_lines = []
        for key, value in edited_fields.items():
            label, _ = EDITABLE_FIELDS[key]
            if key == "status":
                value_display = STATUS_MAP.get(value, value)
            else:
                value_display = value if value != "" else "—"
            summary_lines.append(f"• {label}: {value_display}")

        summary = "\n".join(summary_lines)

        changed_labels = ", ".join(EDITABLE_FIELDS[k][0] for k in edited_fields.keys())
        log_action(
            order.get("OrderID", ""),
            order.get("TrackingCode", ""),
            f"تعديل طلبية ({changed_labels})",
            get_actor_name(update)
        )

        await query.edit_message_text(
            "✅ *تم حفظ التعديلات بنجاح!*\n\n"
            f"🔑 رمز التتبع: `{order.get('TrackingCode', '')}`\n\n"
            "📌 التعديلات التي تمت:\n"
            f"{summary}",
            parse_mode="Markdown"
        )
        context.user_data.clear()
        await show_admin_menu(update, context)
        return ADMIN_MENU

    if data == "back_to_fields":
        text = format_edit_overview(order, edited_fields)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=build_fields_keyboard(edited_fields))
        return EDIT_CHOOSE_FIELD

    if data.startswith("field_"):
        field_key = data.split("_", 1)[1]
        label, _ = EDITABLE_FIELDS[field_key]

        if field_key == "status":
            await query.edit_message_text("📋 اختر الحالة الجديدة للطلب:", reply_markup=build_status_keyboard())
            return EDIT_CHOOSE_FIELD

        if field_key == "cardtype":
            await query.edit_message_text("🃏 اختر نوع البطاقات الجديد:", reply_markup=build_cardtype_keyboard())
            return EDIT_CHOOSE_FIELD

        context.user_data["editing_field"] = field_key
        await query.edit_message_text(
            f"✏️ أرسل القيمة الجديدة لـ *{label}*:\n\n(أرسل /cancel للإلغاء الكامل)",
            parse_mode="Markdown"
        )
        return EDIT_TEXT_INPUT

    if data.startswith("value_"):
        _, field_key, value = data.split("_", 2)
        edited_fields[field_key] = value
        context.user_data["edit_fields"] = edited_fields

        text = format_edit_overview(order, edited_fields)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=build_fields_keyboard(edited_fields))
        return EDIT_CHOOSE_FIELD

    return EDIT_CHOOSE_FIELD


async def edit_receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field_key = context.user_data.get("editing_field")
    if not field_key:
        return EDIT_CHOOSE_FIELD

    new_value = update.message.text.strip()

    edited_fields = context.user_data.get("edit_fields", {})
    edited_fields[field_key] = new_value
    context.user_data["edit_fields"] = edited_fields
    context.user_data.pop("editing_field", None)

    order = context.user_data.get("edit_order", {})
    text = format_edit_overview(order, edited_fields)

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=build_fields_keyboard(edited_fields))
    return EDIT_CHOOSE_FIELD


# ===================== بحث عن طلبية =====================

async def search_order_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.pop("search_type", None)

    buttons = [
        [InlineKeyboardButton("👤 بحث باسم الزبون", callback_data="search_name")],
        [InlineKeyboardButton("🔑 بحث برقم التتبع", callback_data="search_code")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")],
    ]
    await query.edit_message_text(
        "🔍 *بحث عن طلبية*\n\nاختر طريقة البحث:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return SEARCH_CHOOSE_TYPE


async def search_choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "admin_back":
        await query.edit_message_text("🛠️ *لوحة تحكم الأدمن*", parse_mode="Markdown")
        await show_admin_menu(update, context)
        return ADMIN_MENU

    if data == "search_name":
        context.user_data["search_type"] = "name"
        await query.edit_message_text(
            "👤 أرسل اسم الزبون (أو جزء منه) للبحث:\n\n(أرسل /cancel للرجوع)"
        )
        return SEARCH_WAIT_INPUT

    if data == "search_code":
        context.user_data["search_type"] = "code"
        await query.edit_message_text(
            "🔑 أرسل رمز التتبع للبحث:\n\n(أرسل /cancel للرجوع)"
        )
        return SEARCH_WAIT_INPUT

    return SEARCH_CHOOSE_TYPE


async def search_wait_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_type = context.user_data.get("search_type")
    query_text = update.message.text.strip()

    orders = sheet.get_all_records()
    results = []

    if search_type == "code":
        code = query_text.upper()
        for order in orders:
            if order.get("TrackingCode", "").upper() == code:
                results.append(order)
    else:  # name
        name_lower = query_text.lower()
        for order in orders:
            if name_lower in order.get("CustomerName", "").lower():
                results.append(order)

    if not results:
        await update.message.reply_text("❌ لم يتم العثور على أي طلبية مطابقة.")
    elif len(results) == 1:
        await update.message.reply_text(
            f"✅ *تم العثور على الطلبية:*\n\n{format_order_full(results[0])}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"✅ *تم العثور على {len(results)} طلبية مطابقة:*", parse_mode="Markdown")
        for order in results:
            await update.message.reply_text(format_order_full(order), parse_mode="Markdown")

    context.user_data.pop("search_type", None)
    await show_admin_menu(update, context)
    return ADMIN_MENU


# ===================== حذف / أرشفة طلبية =====================

async def delete_order_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🗑️ *حذف/أرشفة طلبية*\n\nأرسل رمز التتبع الخاص بالطلبية التي تريد حذفها.\n\n"
        "(أرسل /cancel للرجوع)",
        parse_mode="Markdown"
    )
    return DELETE_WAIT_CODE


async def delete_receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tracking_code = update.message.text.strip().upper()

    orders = sheet.get_all_records()

    for index, order in enumerate(orders, start=2):
        if order.get("TrackingCode", "").upper() == tracking_code:
            context.user_data["delete_row_index"] = index
            context.user_data["delete_order"] = order

            buttons = [[
                InlineKeyboardButton("✅ تأكيد الحذف والأرشفة", callback_data="del_confirm"),
                InlineKeyboardButton("❌ إلغاء", callback_data="del_cancel"),
            ]]

            await update.message.reply_text(
                f"⚠️ *هل أنت متأكد من حذف وأرشفة هذه الطلبية؟*\n\n{format_order_full(order)}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return DELETE_CONFIRM

    await update.message.reply_text(
        "❌ لم يتم العثور على طلبية بهذا الرمز.\nأعد إرسال الرمز الصحيح أو /cancel للرجوع."
    )
    return DELETE_WAIT_CODE


async def delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "del_confirm":
        row_index = context.user_data.get("delete_row_index")
        order = context.user_data.get("delete_order", {})

        archive_order(order)
        sheet.delete_rows(row_index)

        log_action(
            order.get("OrderID", ""),
            order.get("TrackingCode", ""),
            "حذف الطلبية وأرشفتها",
            get_actor_name(update)
        )

        await query.edit_message_text(
            f"🗑️ *تم حذف الطلبية وأرشفتها بنجاح!*\n\n🔑 رمز التتبع: `{order.get('TrackingCode', '')}`",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("❌ تم إلغاء عملية الحذف.")

    context.user_data.pop("delete_row_index", None)
    context.user_data.pop("delete_order", None)
    await show_admin_menu(update, context)
    return ADMIN_MENU


# ===================== عرض كل الطلبات =====================

async def list_all_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    orders = sheet.get_all_records()

    if not orders:
        await query.edit_message_text("📭 لا يوجد أي طلبات مسجلة حالياً.")
        await show_admin_menu(update, context)
        return ADMIN_MENU

    await query.edit_message_text(f"📋 *إجمالي الطلبات: {len(orders)}*", parse_mode="Markdown")

    chunk_size = 5
    for i in range(0, len(orders), chunk_size):
        chunk = orders[i:i + chunk_size]
        text = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(format_order_full(o) for o in chunk)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")

    await show_admin_menu(update, context)
    return ADMIN_MENU


# ===================== إحصائية الطلبات =====================

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    orders = sheet.get_all_records()
    total = len(orders)

    status_counts = {status: 0 for status in VALID_STATUSES}
    for order in orders:
        status = order.get("Status", "")
        if status in status_counts:
            status_counts[status] += 1
        else:
            status_counts[status] = status_counts.get(status, 0) + 1

    lines = [
        "📊 *إحصائية الطلبات*",
        "",
        f"📦 إجمالي عدد الطلبات: *{total}*",
        "",
        "📌 تفاصيل الحالات:",
    ]

    for status in VALID_STATUSES:
        count = status_counts.get(status, 0)
        lines.append(f"• {STATUS_MAP.get(status, status)}: *{count}*")

    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
    await show_admin_menu(update, context)
    return ADMIN_MENU


# ===================== تحميل ملفات Excel =====================

async def export_menu_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update.effective_user.id):
        await query.edit_message_text("❌ ليس لديك صلاحية لتحميل الملفات.")
        await show_main_menu(update, context)
        return MAIN_MENU

    await query.edit_message_text(
        "📥 *تحميل ملفات Excel*\n\nاختر الملف الذي تريد تحميله:",
        parse_mode="Markdown",
        reply_markup=export_choose_keyboard()
    )
    return EXPORT_CHOOSE


async def export_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "export_back":
        await query.edit_message_text("🛠️ *لوحة تحكم الأدمن*", parse_mode="Markdown")
        await show_admin_menu(update, context)
        return ADMIN_MENU

    sheet_map = {
        "export_Orders": ("Orders", sheet),
        "export_Archive": ("Archive", archive_sheet),
        "export_Logs": ("Logs", logs_sheet),
    }

    if data not in sheet_map:
        return EXPORT_CHOOSE

    sheet_name, ws = sheet_map[data]

    await query.edit_message_text(f"⏳ جاري تجهيز ملف {sheet_name}...")

    try:
        records = ws.get_all_records()
        df = pd.DataFrame(records)

        file_path = os.path.join(
            tempfile.gettempdir(),
            f"{sheet_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        df.to_excel(file_path, index=False)

        with open(file_path, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=f"{sheet_name}.xlsx",
                caption=f"📥 ملف {sheet_name}.xlsx"
            )

        os.remove(file_path)

    except Exception as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ حدث خطأ أثناء تجهيز الملف:\n{e}"
        )

    await show_admin_menu(update, context)
    return ADMIN_MENU


# ===================== قائمة الأدمن - التوجيه =====================

async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "main_back":
        await query.answer()
        await query.edit_message_text("👋 رجعت للقائمة الرئيسية.")
        await show_main_menu(update, context)
        return MAIN_MENU

    if data == "admin_new":
        return await new_order_from_button(update, context)

    if data == "admin_edit":
        return await edit_order_from_button(update, context)

    if data == "admin_search":
        return await search_order_from_button(update, context)

    if data == "admin_delete":
        return await delete_order_from_button(update, context)

    if data == "admin_list":
        return await list_all_orders(update, context)

    if data == "admin_stats":
        return await show_stats(update, context)

    if data == "admin_export":
        return await export_menu_from_button(update, context)

    await query.answer()
    return ADMIN_MENU


# ===================== مراقبة تغييرات الحالة =====================

last_status = {}


async def watch_orders(app):
    """
    Background task: تراقب تغييرات الحالة وترسل إشعارات للزبائن.
    تشتغل كـ asyncio task داخل event loop الخاص بـ PTB.
    """
    global last_status

    while True:
        try:
            orders = sheet.get_all_records()

            for order in orders:
                tracking = order.get("TrackingCode", "")
                status = order.get("Status", "")
                telegram_id = order.get("TelegramID", "")

                if not tracking:
                    continue

                if tracking not in last_status:
                    last_status[tracking] = status
                    continue

                if last_status[tracking] != status:
                    last_status[tracking] = status

                    if telegram_id:
                        status_ar = STATUS_MAP.get(status, status)

                        msg = (
                            f"📦 *تحديث على طلبك*\n\n"
                            f"🔑 رمز التتبع: `{tracking}`\n"
                            f"📋 الحالة الجديدة: {status_ar}"
                        )

                        try:
                            await app.bot.send_message(
                                chat_id=int(telegram_id),
                                text=msg,
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            print(f"خطأ في إرسال الإشعار: {e}")

        except Exception as e:
            print(f"خطأ في watch_orders: {e}")

        await asyncio.sleep(10)


# ===================== تشغيل البوت =====================

async def post_init(app):
    """
    يتم استدعاؤها بعد ما يبدأ البوت وتشتغل داخل event loop الصحيح.
    هون بنشغل background task لمراقبة الطلبات.
    """
    print("Starting watch_orders background task...")
    asyncio.create_task(watch_orders(app))


app = Application.builder().token(TOKEN).post_init(post_init).build()

main_conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        MAIN_MENU: [
            CallbackQueryHandler(main_menu_callback, pattern="^main_"),
        ],
        TRACK_WAIT_CODE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, track_receive_code),
        ],
        ADMIN_MENU: [
            CallbackQueryHandler(admin_menu_callback),
        ],

        # إضافة طلبية
        ASK_NAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
        ASK_PHONE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_city)],
        ASK_CITY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_order)],
        ASK_ORDER:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_total)],
        ASK_TOTAL:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_card_type)],
        ASK_CARD_TYPE: [CallbackQueryHandler(ask_notes, pattern="^newcard_")],
        ASK_NOTES:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_date)],
        ASK_DATE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_order)],
        CONFIRM_ORDER: [CallbackQueryHandler(save_order, pattern="^neworder_")],

        # تعديل طلبية
        EDIT_ASK_CODE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_receive_code)],
        EDIT_CHOOSE_FIELD: [CallbackQueryHandler(edit_choose_field)],
        EDIT_TEXT_INPUT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_receive_text)],

        # بحث عن طلبية
        SEARCH_CHOOSE_TYPE: [CallbackQueryHandler(search_choose_type)],
        SEARCH_WAIT_INPUT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, search_wait_input)],

        # حذف/أرشفة طلبية
        DELETE_WAIT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_receive_code)],
        DELETE_CONFIRM:   [CallbackQueryHandler(delete_confirm, pattern="^del_")],

        # تحميل ملفات Excel
        EXPORT_CHOOSE: [CallbackQueryHandler(export_choose, pattern="^export_")],
    },
    fallbacks=[
        CommandHandler("start", start),
        CommandHandler("cancel", cancel_to_admin_or_main),
    ],
    per_message=False,
)

app.add_handler(main_conv_handler)

print("BOT RUNNING... ✅")

# ===================== إعدادات Render Webhook =====================

PORT = int(os.environ.get("PORT", 10000))
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

if not BASE_URL:
    raise ValueError("RENDER_EXTERNAL_URL not set")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path=WEBHOOK_PATH,
    webhook_url=WEBHOOK_URL,
)