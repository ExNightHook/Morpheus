<?php

if (empty($GLOBALS['SysValue'])) 
{
	exit (header("Location: /"));
}

$url = $SysValue['anypay']['merchant_url'];
$merchant_id = $SysValue['anypay']['merchant_id'];
$o_req = explode("-", $_POST['ouid']);
$pay_id = $o_req[0] . $o_req[1];
$amount = $GLOBALS['SysValue']['other']['total'];
$currency = $SysValue['anypay']['currency'] == 'RUR' ? 'RUB' : $SysValue['anypay']['currency'];
$desc = 'Order #'.$m_orderid;
$secret_key = $SysValue['anypay']['secret_key'];
$sign = md5($currency.':'.$amount.':'.$secret_key.':'.$merchant_id.':'.$pay_id); 

$disp = "
<form action=$url method=POST name=\"pay\">
	<input type=hidden name=merchant_id value=$merchant_id>
	<input type=hidden name=pay_id value=$pay_id>
	<input type=hidden name=amount value=$amount>
	<input type=hidden name=currency value=$currency>
	<input type=hidden name=desc value='$desc'>
	<input type=hidden name=sign value='$sign'>
	<input type=submit value='Оплатить'>
</form>";
?>