Оплата для PHPShop с помощью AnyPay (anypay.io)

Версия: 1.0


Установка:

1. Загрузите содержимое из папки upload в корень сайта.
2. Добавьте в файл /phpshop/inc/config.ini следующие строчки:
[AnyPay] 
merchant_url = "https://anypay.io/merchant"; // url для оплаты
merchant_id = "***"; // ID проекта 
secret_key = "***"; // секретный ключ
currency = "***"; // валюта магазина (RUB, USD, EUR)
paylog = "***"; // путь до файла-журнала (например, /anypay_orders.log) 
emailerror = "***";// email, для отчетов об ошибках 
ipfilter = "***"; // список доверенных ip-адресов через запятую, можно маску
status_success = "4"; // статус заказа после успешной оплаты (4-выполнено) 
status_fail = "1"; // статус заказа после неудачной оплаты (1-аннулирован)

Сохраните изменения в файле.
3. Перейдите в раздел Заказы >> Способы оплаты и нажмите Добавить способ оплаты (плюсик)
4. Заполните поля Наименование - AnyPay, Тип подключения - Оплата AnyPay и сохраните.
5. Установка завершена!



URL для AnyPay:

Result URL    http://ваш_магазин/payment/AnyPAY/status.php
Success URL   http://ваш_магазин/payment/AnyPAY/success.php
Fail URL      http://ваш_магазин/payment/AnyPAY/fail.php

Метод оповещений POST.
