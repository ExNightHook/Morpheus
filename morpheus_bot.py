import os
import json
import threading
import time
import random
import string
import telebot
from telebot import types
from collections import defaultdict

# Конфигурация
TOKEN = "8322158519:AAEWUBMvRauYoKQJA80Z38TeHwwHF9tyXvM"
ADMIN_FILE = "admin.json"
PRODUCTS_DIR = "products"
USERS_FILE = "users.json"

# Инициализация бота
bot = telebot.TeleBot(TOKEN)

# Глобальные переменные
products_cache = {}
maintenance_mode = False
admin_ids = []
user_states = {}  # Для хранения состояний пользователей

# Загрузка конфигурации администраторов
def load_admin_config():
    global maintenance_mode, admin_ids
    try:
        with open(ADMIN_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            admin_ids = config.get("admin_ids", [1143091625])
            maintenance_mode = config.get("maintenance_mode", False)
    except FileNotFoundError:
        default_config = {
            "admin_ids": [1143091625],
            "maintenance_mode": False
        }
        with open(ADMIN_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=4, ensure_ascii=False)
        admin_ids = [1143091625]
        maintenance_mode = False

# Сохранение конфигурации администраторов
def save_admin_config():
    config = {
        "admin_ids": admin_ids,
        "maintenance_mode": maintenance_mode
    }
    with open(ADMIN_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# Загрузка пользователей
def load_users():
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

# Сохранение пользователей
def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

# Добавление пользователя
def add_user(user_id):
    users = load_users()
    if user_id not in users:
        users.append(user_id)
        save_users(users)

# Проверка на администратора
def is_admin(user_id):
    return user_id in admin_ids

# Проверка технических работ
def check_maintenance(message):
    if maintenance_mode and not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⚠️ В настоящее время ведутся технические работы.\nПожалуйста, попробуйте позже.")
        return True
    return False

# Сканирование продуктов
def scan_products():
    global products_cache
    while True:
        try:
            products = {}
            if os.path.exists(PRODUCTS_DIR):
                for item in os.listdir(PRODUCTS_DIR):
                    product_path = os.path.join(PRODUCTS_DIR, item)
                    if os.path.isdir(product_path):
                        loader_path = os.path.join(product_path, "Loader.zip")
                        keys_path = os.path.join(product_path, "keys.txt")
                        
                        if os.path.exists(loader_path) and os.path.exists(keys_path):
                            with open(keys_path, 'r', encoding='utf-8') as f:
                                keys = [line.strip() for line in f if line.strip()]
                            
                            sold_keys_path = os.path.join(product_path, "sold_keys.txt")
                            sold_count = 0
                            if os.path.exists(sold_keys_path):
                                with open(sold_keys_path, 'r', encoding='utf-8') as f:
                                    sold_count = len([line for line in f if line.strip()])
                            
                            products[item] = {
                                "name": item,
                                "available_keys": len(keys),
                                "sold_keys": sold_count,
                                "loader_path": loader_path,
                                "keys_path": keys_path,
                                "sold_keys_path": sold_keys_path
                            }
            
            products_cache = products
            time.sleep(5)
        except Exception as e:
            print(f"Ошибка при сканировании продуктов: {e}")
            time.sleep(10)

# Функция для получения ключа
def get_product_key(product_name):
    try:
        product_info = products_cache.get(product_name)
        if not product_info:
            return None
        
        keys_path = product_info["keys_path"]
        sold_keys_path = product_info["sold_keys_path"]
        
        with open(keys_path, 'r', encoding='utf-8') as f:
            keys = [line.strip() for line in f if line.strip()]
        
        if not keys:
            return None
        
        key = keys[0]
        
        with open(keys_path, 'w', encoding='utf-8') as f:
            for k in keys[1:]:
                f.write(k + '\n')
        
        with open(sold_keys_path, 'a', encoding='utf-8') as f:
            f.write(f"{key}\n")
        
        products_cache[product_name]["available_keys"] -= 1
        products_cache[product_name]["sold_keys"] += 1
        
        return key
    except Exception as e:
        print(f"Ошибка при получении ключа: {e}")
        return None

# Генерация ключей
def generate_keys(product_name, count):
    try:
        product_info = products_cache.get(product_name)
        if not product_info:
            return False, "Продукт не найден"
        
        keys_path = product_info["keys_path"]
        
        new_keys = []
        for i in range(count):
            parts = []
            for _ in range(4):
                parts.append(''.join(random.choices(string.ascii_uppercase + string.digits, k=5)))
            key = f"MPH-{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}"
            new_keys.append(key)
        
        with open(keys_path, 'a', encoding='utf-8') as f:
            for key in new_keys:
                f.write(key + '\n')
        
        products_cache[product_name]["available_keys"] += count
        
        return True, f"Сгенерировано {count} ключей для {product_name}"
    except Exception as e:
        return False, f"Ошибка: {str(e)}"

# Обработка демо-оплаты
def process_demo_payment(user_id, product_name):
    try:
        product_info = products_cache.get(product_name)
        if not product_info:
            return False, None, None
        
        key = get_product_key(product_name)
        if not key:
            return False, None, None
        
        loader_path = product_info["loader_path"]
        
        return True, loader_path, key
    except Exception as e:
        print(f"Ошибка при обработке демо-оплаты: {e}")
        return False, None, None

# Команды бота
@bot.message_handler(commands=['start'])
def start_command(message):
    if check_maintenance(message):
        return
    
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # Добавляем пользователя в список
    add_user(user_id)
    
    welcome_text = f"""👋 Привет, {username}!

Добро пожаловать в магазин лицензионного ПО Morpheus!

🎮 У нас вы найдете:
• Игровые ассистенты
• Модификации для популярных онлайн-игр
• Автоматическую выдачу после оплаты
• Лицензионные ключи по подписке

📦 Все продукты доставляются автоматически после оплаты!

Выберите действие:"""
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('📋 Список продуктов'))
    markup.add(types.KeyboardButton('🛒 Мои покупки'))
    markup.add(types.KeyboardButton('ℹ️ Помощь'))
    
    if is_admin(user_id):
        markup.add(types.KeyboardButton('⚙️ Админ-панель'))
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '📋 Список продуктов')
def show_products(message):
    if check_maintenance(message):
        return
    
    if not products_cache:
        bot.send_message(message.chat.id, "📭 В данный момент товары отсутствуют.")
        return
    
    text = "🎮 **Доступные продукты:**\n\n"
    for product_name, info in products_cache.items():
        text += f"📦 **{product_name}**\n"
        text += f"   • Доступно ключей: {info['available_keys']}\n\n"
    
    text += "Выберите продукт для покупки:"
    
    markup = types.InlineKeyboardMarkup()
    for product_name in products_cache.keys():
        markup.add(types.InlineKeyboardButton(
            text=f"🛒 {product_name}",
            callback_data=f"select_product:{product_name}"
        ))
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '🛒 Мои покупки')
def my_purchases(message):
    if check_maintenance(message):
        return
    
    bot.send_message(message.chat.id, 
                    "🔍 Функция просмотра покупок будет доступна в следующем обновлении.\n"
                    "Все приобретенные ключи отправляются вам сразу после оплаты.")

@bot.message_handler(func=lambda message: message.text == 'ℹ️ Помощь')
def help_command(message):
    if check_maintenance(message):
        return
    
    help_text = """❓ **Помощь и поддержка**

**Как купить:**
1. Выберите продукт из списка
2. Выберите способ оплаты (временно доступна только демо-оплата)
3. Получите архив с программой и ключ активации

**Что делать после покупки:**
1. Скачайте и распакуйте архив
2. Запустите программу
3. Введите полученный ключ активации
4. Следуйте инструкциям в программе

**Важно:**
• Ключи активации одноразовые
• Каждый ключ привязан к устройству
• Поддержка работает 24/7

Для связи с поддержкой: @MorpheusPrivate"""
    
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '⚙️ Админ-панель' and is_admin(message.from_user.id))
def admin_panel(message):
    if check_maintenance(message):
        return
    
    if not is_admin(message.from_user.id):
        return
    
    text = f"""⚙️ **Админ-панель**

Статус технических работ: {'🔴 ВКЛЮЧЕН' if maintenance_mode else '🟢 ВЫКЛЮЧЕН'}
Количество продуктов: {len(products_cache)}
Администраторов: {len(admin_ids)}

**Доступные действия:**"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            '🔄 Обновить статус ТР' if not maintenance_mode else '✅ Выключить ТР',
            callback_data='toggle_maintenance'
        ),
        types.InlineKeyboardButton('📢 Сделать рассылку', callback_data='broadcast'),
        types.InlineKeyboardButton('📊 Статистика', callback_data='stats'),
        types.InlineKeyboardButton('➕ Добавить админа', callback_data='add_admin'),
        types.InlineKeyboardButton('🔑 Генерировать ключи', callback_data='generate_keys')
    )
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='Markdown')

# Обработка инлайн-кнопок
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    
    if maintenance_mode and not is_admin(user_id):
        bot.answer_callback_query(call.id, "⚠️ Ведутся технические работы!")
        return
    
    if call.data.startswith('select_product:'):
        product_name = call.data.split(':')[1]
        show_product_details(call.message, product_name)
    
    elif call.data == 'back_to_products':
        show_products_back(call.message)
    
    elif call.data == 'demo_payment':
        process_payment(call.message, user_id)
    
    elif call.data == 'toggle_maintenance':
        if is_admin(user_id):
            toggle_maintenance(call.message)
        else:
            bot.answer_callback_query(call.id, "❌ Нет доступа!")
    
    elif call.data == 'broadcast':
        if is_admin(user_id):
            ask_broadcast_message(call.message)
        else:
            bot.answer_callback_query(call.id, "❌ Нет доступа!")
    
    elif call.data == 'stats':
        if is_admin(user_id):
            show_stats(call.message)
        else:
            bot.answer_callback_query(call.id, "❌ Нет доступа!")
    
    elif call.data == 'add_admin':
        if is_admin(user_id):
            ask_admin_id(call.message)
        else:
            bot.answer_callback_query(call.id, "❌ Нет доступа!")
    
    elif call.data == 'generate_keys':
        if is_admin(user_id):
            ask_product_for_keys(call.message)
        else:
            bot.answer_callback_query(call.id, "❌ Нет доступа!")
    
    elif call.data.startswith('generate_for:'):
        if is_admin(user_id):
            product_name = call.data.split(':')[1]
            ask_keys_count(call.message, product_name)
        else:
            bot.answer_callback_query(call.id, "❌ Нет доступа!")

def show_product_details(message, product_name):
    product_info = products_cache.get(product_name)
    if not product_info:
        bot.send_message(message.chat.id, "❌ Продукт не найден!")
        return
    
    text = f"""📦 **{product_name}**

📝 **Описание:**
Игровой ассистент с автоматической выдачей ключей.

⚙️ **Характеристики:**
• Автоматическая активация
• Ежемесячное обновление
• Техническая поддержка
• Автовыдача ключей

📊 **Доступность:**
• Свободных ключей: {product_info['available_keys']}

💰 **Стоимость:** Демо-версия (бесплатно)

Выберите способ оплаты:"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        text='🟢 Демо-оплата (бесплатно)',
        callback_data='demo_payment'
    ))
    markup.add(types.InlineKeyboardButton(
        text='↩️ Назад к продуктам',
        callback_data='back_to_products'
    ))
    
    # Сохраняем выбранный продукт в состоянии пользователя
    user_states[message.chat.id] = {'selected_product': product_name}
    
    if message.content_type == 'text':
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message.message_id,
            text=text,
            reply_markup=markup,
            parse_mode='Markdown'
        )

def show_products_back(message):
    if not products_cache:
        bot.send_message(message.chat.id, "📭 В данный момент товары отсутствуют.")
        return
    
    text = "🎮 **Доступные продукты:**\n\n"
    for product_name, info in products_cache.items():
        text += f"📦 **{product_name}**\n"
        text += f"   • Доступно ключей: {info['available_keys']}\n\n"
    
    text += "Выберите продукт для покупки:"
    
    markup = types.InlineKeyboardMarkup()
    for product_name in products_cache.keys():
        markup.add(types.InlineKeyboardButton(
            text=f"🛒 {product_name}",
            callback_data=f"select_product:{product_name}"
        ))
    
    if message.content_type == 'text':
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message.message_id,
            text=text,
            reply_markup=markup,
            parse_mode='Markdown'
        )

def process_payment(message, user_id):
    # Получаем выбранный продукт из состояния пользователя
    selected_product = None
    if message.chat.id in user_states:
        selected_product = user_states[message.chat.id].get('selected_product')
    
    # Если продукт не найден в состоянии, берем первый доступный
    if not selected_product and products_cache:
        selected_product = list(products_cache.keys())[0]
    
    if not selected_product:
        bot.send_message(message.chat.id, "❌ Нет доступных продуктов!")
        return
    
    # Обрабатываем демо-оплату
    success, loader_path, key = process_demo_payment(user_id, selected_product)
    
    if success:
        try:
            with open(loader_path, 'rb') as file:
                bot.send_document(
                    chat_id=message.chat.id,
                    document=file,
                    caption=f"✅ **Оплата прошла успешно!**\n\n"
                           f"📦 Продукт: {selected_product}\n"
                           f"🔑 Ключ активации:\n`{key}`\n\n"
                           f"⚠️ **Важно:**\n"
                           f"• Сохраните ключ в надежном месте\n"
                           f"• Ключ можно использовать только один раз\n"
                           f"• При возникновении проблем обращайтесь в поддержку",
                    parse_mode='Markdown'
                )
            
            instruction = """📋 **Инструкция по активации:**

1. Распакуйте архив Loader.zip
2. Запустите программу
3. Введите ключ активации в соответствующее поле
4. Следуйте инструкциям программы

🔄 **Для повторной загрузки:**
Ключ отправляется только один раз. Сохраните его!

❓ **Поддержка:** @MorpheusPrivate"""
            
            bot.send_message(message.chat.id, instruction, parse_mode='Markdown')
            
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка при отправке файла: {str(e)}")
    else:
        bot.send_message(message.chat.id, "❌ Не удалось обработать оплату. Нет доступных ключей!")

# Админские функции
def toggle_maintenance(message):
    global maintenance_mode
    maintenance_mode = not maintenance_mode
    save_admin_config()
    
    status = "включены" if maintenance_mode else "выключены"
    bot.send_message(message.chat.id, f"✅ Технические работы {status}!")
    admin_panel(message)

def ask_broadcast_message(message):
    msg = bot.send_message(message.chat.id, "✍️ Введите сообщение для рассылки:")
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    if not is_admin(message.from_user.id):
        return
    
    broadcast_text = message.text
    bot.send_message(message.chat.id, f"📢 Начинаю рассылку сообщения...")
    
    # Загружаем всех пользователей
    users = load_users()
    sent_count = 0
    error_count = 0
    
    for user_id in users:
        try:
            bot.send_message(user_id, f"📢 **Рассылка от администратора:**\n\n{broadcast_text}", parse_mode='Markdown')
            sent_count += 1
            time.sleep(0.1)  # Чтобы не превысить лимиты Telegram
        except Exception as e:
            error_count += 1
            print(f"Ошибка при отправке пользователю {user_id}: {e}")
    
    bot.send_message(message.chat.id, 
                    f"✅ Рассылка завершена!\n"
                    f"📤 Отправлено: {sent_count}\n"
                    f"❌ Ошибок: {error_count}")

def show_stats(message):
    total_products = len(products_cache)
    total_keys = sum(p['available_keys'] + p['sold_keys'] for p in products_cache.values())
    available_keys = sum(p['available_keys'] for p in products_cache.values())
    sold_keys = sum(p['sold_keys'] for p in products_cache.values())
    
    stats_text = f"""📊 **Статистика магазина**

📦 Продуктов: {total_products}
🔑 Всего ключей: {total_keys}
🟢 Доступно ключей: {available_keys}
💰 Продано ключей: {sold_keys}
📈 Процент продаж: {round((sold_keys/total_keys*100) if total_keys > 0 else 0, 1)}%

**По продуктам:**\n"""
    
    for product_name, info in products_cache.items():
        total = info['available_keys'] + info['sold_keys']
        stats_text += f"\n{product_name}:\n"
        stats_text += f"  Продано: {info['sold_keys']}/{total} "
        stats_text += f"({round((info['sold_keys']/total*100) if total > 0 else 0, 1)}%)\n"
    
    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')

def ask_admin_id(message):
    msg = bot.send_message(message.chat.id, "👤 Введите ID нового администратора:")
    bot.register_next_step_handler(msg, add_admin)

def add_admin(message):
    if not is_admin(message.from_user.id):
        return
    
    try:
        new_admin_id = int(message.text)
        if new_admin_id not in admin_ids:
            admin_ids.append(new_admin_id)
            save_admin_config()
            bot.send_message(message.chat.id, f"✅ Администратор {new_admin_id} добавлен!")
        else:
            bot.send_message(message.chat.id, "⚠️ Этот администратор уже есть в списке!")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат ID!")

def ask_product_for_keys(message):
    if not products_cache:
        bot.send_message(message.chat.id, "📭 Нет доступных продуктов!")
        return
    
    text = "🔑 **Генерация ключей**\n\nВыберите продукт:"
    
    markup = types.InlineKeyboardMarkup()
    for product_name in products_cache.keys():
        markup.add(types.InlineKeyboardButton(
            text=product_name,
            callback_data=f"generate_for:{product_name}"
        ))
    
    bot.send_message(message.chat.id, text, reply_markup=markup)

def ask_keys_count(message, product_name):
    msg = bot.send_message(message.chat.id, f"🔢 Введите количество ключей для генерации в {product_name}:")
    bot.register_next_step_handler(msg, lambda m: generate_keys_handler(m, product_name))

def generate_keys_handler(message, product_name):
    if not is_admin(message.from_user.id):
        return
    
    try:
        count = int(message.text)
        if count <= 0:
            bot.send_message(message.chat.id, "❌ Количество должно быть положительным числом!")
            return
        if count > 1000:
            bot.send_message(message.chat.id, "❌ Максимальное количество - 1000 ключей за раз!")
            return
        
        success, result = generate_keys(product_name, count)
        if success:
            bot.send_message(message.chat.id, f"✅ {result}")
        else:
            bot.send_message(message.chat.id, f"❌ {result}")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат числа!")

# Обработка всех сообщений
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    if check_maintenance(message):
        return
    
    if message.text.startswith('/'):
        bot.send_message(message.chat.id, "ℹ️ Используйте кнопки меню для навигации")
    else:
        bot.send_message(message.chat.id, 
                        "🤖 Я не понимаю текстовые команды. Используйте кнопки меню!")

# Запуск сканирования продуктов в отдельном потоке
def start_product_scanner():
    scanner_thread = threading.Thread(target=scan_products, daemon=True)
    scanner_thread.start()

# Основная функция
def main():
    print("🚀 Запуск бота Morpheus...")
    
    # Загружаем конфигурацию
    load_admin_config()
    
    # Создаем необходимые папки
    if not os.path.exists(PRODUCTS_DIR):
        os.makedirs(PRODUCTS_DIR)
        print(f"📁 Создана папка {PRODUCTS_DIR}")
    
    # Запускаем сканер продуктов
    start_product_scanner()
    
    print("✅ Бот запущен и готов к работе!")
    print(f"👑 Администраторы: {admin_ids}")
    print(f"⚠️ Технические работы: {'ВКЛЮЧЕНЫ' if maintenance_mode else 'ВЫКЛЮЧЕНЫ'}")
    print(f"📦 Автосканирование продуктов: ВКЛЮЧЕНО (каждые 5 секунд)")
    
    # Запускаем бота
    bot.polling(none_stop=True, interval=0)

if __name__ == "__main__":
    main()