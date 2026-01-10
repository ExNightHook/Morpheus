# Исправления и инструкции

## Исправленные проблемы

### 1. Ошибка "Incorrect merchant ID"
**Проблема:** NicePay возвращал ошибку "Incorrect merchant ID"

**Исправление:**
- Добавлена очистка пробелов из merchant_id и secret_key
- Добавлено логирование параметров для отладки
- Улучшена обработка ошибок API

**Проверка:** Убедитесь, что в `.env` файле:
```env
NICEPAY_MERCHANT_ID=696179391f37cffbecb0afbd
NICEPAY_SECRET_KEY=b4UaD-BPAK9-sinXx-41W3q-ZNctr
```
Без пробелов в начале и конце!

### 2. Добавлены методы оплаты RUB
**Добавлены все методы оплаты:**
- СБП (sbp_rub, sbp)
- Банки: Сбербанк, Tinkoff, Альфа-Банк, ВТБ, и др.
- Кошельки: ЮMoney, AdvCash, Payeer

**Проверка минимальной суммы для СБП:**
- Добавлена проверка: минимальная сумма 200 рублей
- Если пользователь пытается оплатить через СБП сумму менее 200₽, бот выдаст ошибку

### 3. Исправление скрипта morpheus
**Проблема:** Скрипт не запускался с ошибкой "No such file or directory"

**Решение:**

Выполните на сервере:
```bash
cd /opt/Morpheus
sudo chmod +x morpheus
sudo cp morpheus /usr/local/bin/morpheus
sudo chmod +x /usr/local/bin/morpheus

# Проверьте формат файла (должен быть LF, не CRLF)
sudo sed -i 's/\r$//' /usr/local/bin/morpheus

# Проверьте shebang
head -n 1 /usr/local/bin/morpheus
# Должно быть: #!/bin/bash

# Если shebang неправильный, исправьте:
sudo sed -i '1s|^.*|#!/bin/bash|' /usr/local/bin/morpheus
```

Или используйте готовый скрипт:
```bash
cd /opt/Morpheus
sudo bash fix_morpheus.sh
```

После этого проверьте:
```bash
sudo morpheus -help
sudo morpheus -admin
```

### 4. Удалены все упоминания AnyPay
- Удален файл `backend/app/services/anypay.py`
- Обновлены все конфигурации
- Обновлен README.md
- Обновлен deploy/install.sh

## Настройка методов оплаты

В файле `.env` укажите доступные методы:
```env
NICEPAY_METHODS=sbp_rub,sberbank_rub,tinkoff_rub,alfabank_rub,vtb_rub,yoomoney_rub,advcash_rub,payeer_rub
```

Доступные методы RUB:
- `sbp_rub` - СБП по QR
- `sbp` - СБП
- `sberbank_rub` - Сбербанк на карту
- `sberbank_account_rub` - Сбербанк по счёту
- `tinkoff_rub` - Tinkoff
- `alfabank_rub` - Альфа-Банк
- `raiffeisen_rub` - Райффайзен
- `vtb_rub` - ВТБ
- `yoomoney_rub` - ЮMoney
- `advcash_rub` - AdvCash
- `payeer_rub` - Payeer
- И другие (см. список в коде)

## Webhook URL для NicePay

В настройках мерчанта NicePay укажите:
```
https://64.188.65.244/payments/nicepay/webhook
```

## Важные замечания

1. **Валюта определяется автоматически** по методу оплаты (_rub, _usd, _eur и т.д.)
2. **Минимальная сумма для СБП:** 200 рублей (проверка добавлена)
3. **IP адрес вместо домена:** Используется `https://64.188.65.244` с самоподписным сертификатом
4. **Курсы валют:** Сейчас используются примерные курсы. Для продакшена нужно добавить реальные курсы или использовать API курсов валют

## После обновления

1. Обновите `.env` файл с правильными данными NicePay
2. Перезапустите сервисы:
   ```bash
   sudo morpheus -restart
   ```
3. Проверьте логи:
   ```bash
   sudo morpheus -logs api 50
   ```
4. Проверьте доступ к админ-панели:
   ```bash
   sudo morpheus -admin
   ```
