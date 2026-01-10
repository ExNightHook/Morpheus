<?php
function UpdateNumOrder($uid)
{
	$last_num = substr($uid, -2);
	$total = strlen($uid);
	$ferst_num = substr($uid, 0, ($total-2));
	return $ferst_num . "-" . $last_num;
}

$SysValue = parse_ini_file("../../phpshop/inc/config.ini", 1);

while(list($section,$array) = each($SysValue))
{
	while(list($key,$value) = each($array))
	{
		$SysValue['other'][chr(73) . chr(110) . chr(105) . ucfirst(strtolower($section)) . ucfirst(strtolower($key))] = $value;
	}
}

if (isset($_REQUEST["pay_id"]) && isset($_REQUEST["sign"]))
{
	$err = false;
	$message = '';
	$amount = $_REQUEST['amount'];
	$pay_id = $_REQUEST['pay_id'];
	
	// запись логов

	$log_text = 
	"--------------------------------------------------------\n" .
	"operation id       " . $_REQUEST['pay_id'] . "\n" .
	"shop               " . $_REQUEST['merchant_id'] . "\n" .
	"amount             " . $_REQUEST['amount'] . "\n" .
	"currency           " . $_REQUEST['method'] . "\n" .
	"description        " . $_REQUEST['desc'] . "\n" .
	"sign               " . $_REQUEST['sign'] . "\n\n";
	
	$log_file = $SysValue['anypay']['paylog'];
	
	if (!empty($log_file))
	{
		file_put_contents($_SERVER['DOCUMENT_ROOT'] . $log_file, $log_text, FILE_APPEND);
	}

	// проверка цифровой подписи и ip
	
	$valid_ip = true;
	$sIP = str_replace(' ', '', $SysValue['anypay']['ipfilter']);
	
	if (!empty($sIP))
	{
		$arrIP = explode('.', $_SERVER['REMOTE_ADDR']);
		if (!preg_match('/(^|,)(' . $arrIP[0] . '|\*{1})(\.)' .
		'(' . $arrIP[1] . '|\*{1})(\.)' .
		'(' . $arrIP[2] . '|\*{1})(\.)' .
		'(' . $arrIP[3] . '|\*{1})($|,)/', $sIP))
		{
			$valid_ip = false;
		}
	}
	
	if (!$valid_ip)
	{
		$message .= " - ip-адрес не является доверенным\n" .
		"   доверенные ip-адреса: " . $sIP . "\n" .
		"   текущий ip-адрес: " . $_SERVER['REMOTE_ADDR'] . "\n";
		$err = true;
	}

		$hash = md5($SysValue['anypay']['merchant_id'].':'.$_REQUEST['amount'].':'.$_REQUEST['pay_id'].':'.$SysValue['anypay']['secret_key']);

	if ($_REQUEST['sign'] != $hash)
	{
		$message .= " - не совпадают цифровые подписи\n";
		$err = true;
	}

	if (!$err)
	{
		// загрузка заказа
		
		$new_uid = UpdateNumOrder($_REQUEST["pay_id"]);
	
		@mysql_connect ($SysValue['connect']['host'], $SysValue['connect']['user_db'],  $SysValue['connect']['pass_db']) or 
			@die("" . PHPSHOP_error(101, $SysValue['my']['error_tracer']) . "");

		@mysql_select_db ($SysValue['connect']['dbase']) or 
			@die("" . PHPSHOP_error(102, $SysValue['my']['error_tracer']) . "");
			
		$sql = "select * from " . $SysValue['base']['table_name1'] . " where uid='$new_uid'";
		$result = mysql_query($sql);
		$row = mysql_fetch_array($result);

		if ($uid == $row['uid'])
		{
			$message .= " - несуществующий ордер\n";
			$err = true;
		}
		else
		{
			$order_curr = ($SysValue['payeer']['currency'] == 'RUR') ? 'RUB' : $SysValue['payeer']['currency'];
			$order_amount = $row['sum'];
			
			// проверка суммы и валюты
		
			if ($_REQUEST['amount'] < $order_amount)
			{
				$message .= " - неправильная сумма\n";
				$err = true;
			}
			
			// проверка статуса
			
			if ($_REQUEST['status'] != 'paid')
			{
				$message .= " - статус платежа не является paid\n";
				$err = true;
			}

			if (!$err)
			{
					
						$status_success = $SysValue['anypay']['status_success'];
						
						if ($row['statusi'] != $status_success)
						{
							$sql = "INSERT INTO " . $SysValue['base']['table_name33'] . " VALUES 
								('$pay_id','AnyPay','$amount','" . date("U") . "')";
							
							$result = mysql_query($sql);
							
							$sql = "UPDATE " . $SysValue['base']['table_name1'] . " SET statusi='$status_success' WHERE uid='$new_uid'";
							$result = mysql_query($sql);
						}

			}
		}
	}
	
	if ($err)
	{
		$to = $SysValue['anypay']['emailerror'];

		if (!empty($to))
		{
			$message = "Не удалось провести платёж через систему AnyPay по следующим причинам:\n\n" . $message . "\n" . $log_text;
			$headers = "From: no-reply@" . $_SERVER['HTTP_HOST'] . "\r\n" . 
			"Content-type: text/plain; charset=utf-8 \r\n";
			mail($to, 'Ошибка оплаты', $message, $headers);
		}
		
		exit ($pay_id . "|error");
	}
	else
	{
		exit ($pay_id . "|success");
	}
}
?>