<?php
/**
 * smtp2mqtt - Public Web Entry Point Redirect
 * 
 * In LoxBerry architecture:
 * - /admin/plugins/<plugin>/ (webfrontend/htmlauth/) is protected with user authentication.
 * - /plugins/<plugin>/ (webfrontend/html/) is public and unauthenticated.
 * 
 * To prevent unauthorized access to configuration, JSON status, or credentials,
 * any public request is securely redirected to the authenticated admin endpoint.
 */

$query_string = !empty($_SERVER['QUERY_STRING']) ? ('?' . $_SERVER['QUERY_STRING']) : '';
$admin_url = '/admin/plugins/smtp2mqtt/index.php' . $query_string;

header("Location: " . $admin_url, true, 302);
exit;
