<?php
// php -S router: serve real files, send everything else through WordPress.
$path = parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH );
if ( '/' !== $path && is_file( __DIR__ . $path ) && ! str_ends_with( $path, '.php' ) ) {
	return false;
}
$_SERVER['SCRIPT_NAME'] = '/index.php';
require __DIR__ . '/index.php';
