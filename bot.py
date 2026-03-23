import os
import io
import logging
from urllib.parse import urljoin

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var missing. Set it in Render Environment.")

user_images: dict[int, bytes] = {}


def main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✂️ Crop & Round", callback_data="round"),
            InlineKeyboardButton("🪄 BG Remove", callback_data="bg_remove"),
        ],
        [
            InlineKeyboardButton("🎭 Sticker (WebP)", callback_data="sticker"),
            InlineKeyboardButton("✨ Enhance", callback_data="enhance"),
        ],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)


def enhance_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🔼 2x Upscale", callback_data="enhance_2x"),
            InlineKeyboardButton("🔼 4x Upscale", callback_data="enhance_4x"),
        ],
        [
            InlineKeyboardButton("🌟 Sharp + Vivid", callback_data="enhance_vivid"),
            InlineKeyboardButton("🧼 Denoise", callback_data="enhance_denoise"),
        ],
        [InlineKeyboardButton("💎 Full Enhance", callback_data="enhance_full")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def round_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🔵 Small (30px)", callback_data="round_30"),
            InlineKeyboardButton("🔵 Medium (80px)", callback_data="round_80"),
            InlineKeyboardButton("🔵 Large (150px)", callback_data="round_150"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def apply_rounded_corners(img_bytes: bytes, radius: int = 80) -> bytes:
    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    w, h = img.size
    m = int(min(w, h) * 0.02)
    img = img.crop((m, m, w - m, h - m))
    w, h = img.size

    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (w, h)], radius=radius, fill=255)

    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    result.paste(img, mask=mask)

    out = io.BytesIO()
    result.save(out, "PNG")
    out.seek(0)
    return out.read()


def remove_background(img_bytes: bytes) -> bytes:
    import requests as req

    remove_bg_key = os.environ.get("REMOVE_BG_KEY", "")
    if not remove_bg_key:
        raise RuntimeError("REMOVE_BG_KEY env var missing. Add it in Render Environment.")

    response = req.post(
        "https://api.remove.bg/v1.0/removebg",
        files={"image_file": ("image.png", io.BytesIO(img_bytes), "image/png")},
        data={"size": "auto"},
        headers={"X-Api-Key": remove_bg_key},
        timeout=30,
    )
    if response.status_code == 200:
        return response.content
    raise RuntimeError(f"Remove.bg error: {response.status_code} — {response.text}")


def enhance_quality(img_bytes: bytes, mode: str = "full") -> bytes:
    """
    Enhance image quality.

    mode:
      - '2x', '4x'      : upscale
      - 'vivid'         : sharp + color + contrast
      - 'denoise'       : median filter + mild sharpen
      - 'full'          : 2x upscale + sharpen + color/contrast/brightness + unsharp mask
    """
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = img.size

    if mode == "2x":
        img = img.resize((w * 2, h * 2), Image.LANCZOS)
    elif mode == "4x":
        img = img.resize((w * 4, h * 4), Image.LANCZOS)
    elif mode == "vivid":
        img = ImageEnhance.Sharpness(img).enhance(2.5)
        img = ImageEnhance.Color(img).enhance(1.4)
        img = ImageEnhance.Contrast(img).enhance(1.3)
    elif mode == "denoise":
        img = img.filter(ImageFilter.MedianFilter(size=3))
        img = ImageEnhance.Sharpness(img).enhance(1.5)
    elif mode == "full":
        img = img.resize((w * 2, h * 2), Image.LANCZOS)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        img = ImageEnhance.Color(img).enhance(1.3)
        img = ImageEnhance.Contrast(img).enhance(1.2)
        img = ImageEnhance.Brightness(img).enhance(1.05)
        img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))

    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    out.seek(0)
    return out.read()


def make_sticker(img_bytes: bytes, bg_remove: bool = True) -> bytes:
    """Convert image to Telegram-compatible sticker (WebP, 512px)."""
    try:
        if bg_remove:
            from rembg import remove  # optional dependency
            img_bytes = remove(img_bytes)
    except ImportError:
        pass

    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    img.thumbnail((512, 512), Image.LANCZOS)

    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    offset = ((512 - img.width) // 2, (512 - img.height) // 2)
    canvas.paste(img, offset, img)

    out = io.BytesIO()
    canvas.save(out, "WEBP")
    out.seek(0)
    return out.read()


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🖼️ *Image Editor Bot*\n\nPhoto bhejo aur neeche se feature choose karo! 👇",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )


async def help_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *How to use:*\n\n"
        "1️⃣ `/start` — Main menu kholo\n"
        "2️⃣ Photo bhejo (bot store kar lega)\n"
        "3️⃣ Button press karo → edited image wapas milegi\n\n"
        "*Features:*\n"
        "✂️ *Crop & Round* — Corners round karta hai\n"
        "🪄 *BG Remove* — Background hatata hai\n"
        "🎭 *Sticker* — Telegram sticker (WebP) banata hai\n"
        "✨ *Enhance* — Quality boost karta hai\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())


async def receive_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)

    buf = io.BytesIO()
    await file.download_to_memory(buf)
    user_images[uid] = buf.getvalue()

    await update.message.reply_text(
        "✅ *Photo receive ho gayi!*\nAb feature choose karo 👇",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )


async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data == "back":
        await query.edit_message_text(
            "🖼️ *Image Editor Bot*\n\nFeature choose karo 👇",
            parse_mode="Markdown",
            reply_markup=main_menu(),
        )
        return

    if data == "help":
        await query.edit_message_text(
            "📖 *How to use:*\n\n"
            "1️⃣ Pehle photo bhejo\n"
            "2️⃣ Phir button press karo\n\n"
            "*Features:*\n"
            "✂️ Crop & Round — corners round\n"
            "🪄 BG Remove — background remove\n"
            "🎭 Sticker — WebP sticker bana\n",
            parse_mode="Markdown",
            reply_markup=main_menu(),
        )
        return

    if data == "round":
        await query.edit_message_text(
            "🔵 *Corner radius choose karo:*",
            parse_mode="Markdown",
            reply_markup=round_menu(),
        )
        return

    if data == "enhance":
        await query.edit_message_text(
            "✨ *Enhancement type choose karo:*\n\n"
            "🔼 *2x / 4x* — Size bada karo (upscale)\n"
            "🌟 *Sharp + Vivid* — Sharp aur colorful banao\n"
            "🧼 *Denoise* — Noise / blur hatao\n"
            "💎 *Full Enhance* — Sab kuch ek saath (best!)",
            parse_mode="Markdown",
            reply_markup=enhance_menu(),
        )
        return

    if uid not in user_images:
        await query.edit_message_text(
            "⚠️ Pehle ek *photo bhejo*, phir feature use karo!",
            parse_mode="Markdown",
            reply_markup=main_menu(),
        )
        return

    img_bytes = user_images[uid]

    if data.startswith("round_"):
        radius = int(data.split("_")[1])
        await query.edit_message_text(f"⏳ Rounding corners ({radius}px)...")
        try:
            result = apply_rounded_corners(img_bytes, radius)
            await ctx.bot.send_document(
                chat_id=uid,
                document=io.BytesIO(result),
                filename="rounded.png",
                caption=f"✅ Rounded corners ({radius}px) done!",
            )
        except Exception as exc:
            await ctx.bot.send_message(uid, f"❌ Error: {exc}")
        await ctx.bot.send_message(uid, "Kuch aur karna hai?", reply_markup=main_menu())
        return

    if data == "bg_remove":
        await query.edit_message_text("⏳ Background remove ho raha hai... (thoda time lagega)")
        try:
            result = remove_background(img_bytes)
            await ctx.bot.send_document(
                chat_id=uid,
                document=io.BytesIO(result),
                filename="no_bg.png",
                caption="✅ Background remove ho gaya!",
            )
        except Exception as exc:
            await ctx.bot.send_message(uid, f"❌ Error: {exc}")
        await ctx.bot.send_message(uid, "Kuch aur karna hai?", reply_markup=main_menu())
        return

    if data.startswith("enhance_"):
        mode = data.split("_", maxsplit=1)[1]
        mode_labels = {
            "2x": "2x Upscale",
            "4x": "4x Upscale",
            "vivid": "Sharp + Vivid",
            "denoise": "Denoise",
            "full": "Full Enhance 💎",
        }
        label = mode_labels.get(mode, mode)
        await query.edit_message_text(f"⏳ *{label}* ho raha hai...", parse_mode="Markdown")
        try:
            result = enhance_quality(img_bytes, mode)
            await ctx.bot.send_document(
                chat_id=uid,
                document=io.BytesIO(result),
                filename=f"enhanced_{mode}.png",
                caption=f"✨ *{label}* ho gaya!\n📌 High quality PNG mein save karo.",
                parse_mode="Markdown",
            )
        except Exception as exc:
            await ctx.bot.send_message(uid, f"❌ Error: {exc}")
        await ctx.bot.send_message(uid, "Kuch aur karna hai?", reply_markup=main_menu())
        return

    if data == "sticker":
        await query.edit_message_text("⏳ Sticker ban raha hai...")
        try:
            result = make_sticker(img_bytes)
            await ctx.bot.send_document(
                chat_id=uid,
                document=io.BytesIO(result),
                filename="sticker.webp",
                caption="🎭 Sticker ready! Telegram Sticker Pack mein add kar sakte ho.",
            )
        except Exception as exc:
            await ctx.bot.send_message(uid, f"❌ Error: {exc}")
        await ctx.bot.send_message(uid, "Kuch aur karna hai?", reply_markup=main_menu())
        return


def _get_base_url() -> str | None:
    return os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("WEBHOOK_BASE_URL")


def main():
    port = int(os.environ.get("PORT", "10000"))

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.PHOTO, receive_photo))
    application.add_handler(CallbackQueryHandler(button_handler))

    base_url = _get_base_url()
    if not base_url:
        logging.info("No RENDER_EXTERNAL_URL/WEBHOOK_BASE_URL -> running polling.")
        application.run_polling()
        return

    url_path = f"webhook/{BOT_TOKEN}"
    webhook_url = urljoin(base_url.rstrip("/") + "/", url_path)

    logging.info("Webhook URL: %s", webhook_url)
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=url_path,
        webhook_url=webhook_url,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
