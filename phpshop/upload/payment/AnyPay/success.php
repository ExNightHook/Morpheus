<?php
if (isset($_REQUEST['pay_id']))
{
	$order_id = preg_replace('/[^a-zA-Z0-9_-]/', '', substr($_REQUEST['pay_id'], 0, 32));
	header("Location: " . $SysValue['dir']['dir'] . "/users/order.html?orderId=" . $order_id . "#PphpshopOrder");
}
?>
