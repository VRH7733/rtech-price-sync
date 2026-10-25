<?php
// Run with: wp eval-file live_returns_pages.php
// The live site on 25 Oct 2026: WooCommerce's sample Refund and Returns Policy published, the shop's
// own Return & Cancellation Policy published since September, the plugin's Returns and Refunds draft.
$sample = get_page_by_path( 'refund_returns' );
if ( ! $sample ) {
	$id     = wp_insert_post( array( 'post_type' => 'page', 'post_title' => 'Refund and Returns Policy', 'post_name' => 'refund_returns', 'post_status' => 'draft', 'post_content' => '<p><b>This is a sample page.</b></p><p>Our refund and returns policy lasts 30 days.</p>' ) );
	$sample = get_post( $id );
}
wp_update_post( array( 'ID' => $sample->ID, 'post_status' => 'publish' ) );
wp_insert_post( array( 'post_type' => 'page', 'post_title' => 'Return & Cancellation Policy', 'post_name' => 'return-cancellation-policy', 'post_status' => 'publish', 'post_content' => '<p>Old policy text from September.</p>' ) );
if ( ! get_page_by_path( 'returns-and-refunds' ) ) {
	wp_insert_post( array( 'post_type' => 'page', 'post_title' => 'Returns and Refunds', 'post_name' => 'returns-and-refunds', 'post_status' => 'draft', 'post_content' => '<p>draft</p>' ) );
}
// as if the site still ran 1.0.6: the next request runs the 1.0.7 update steps
update_option( 'rtech_ai_version', '1.0.6' );
echo "sample={$sample->ID}\n";

// Also before 1.1.0 (25 Oct 2026): every payment method off, phone optional, no delivery step at
// checkout, the plugin's delivery page published saying "We do not deliver", and the shop's
// 7 Sep pages: a delivery policy promising delivery in 24-48 hours and another grievance officer.
foreach ( array( 'bacs', 'cheque', 'cod' ) as $g ) {
	$o            = get_option( "woocommerce_{$g}_settings", array() );
	$o            = is_array( $o ) ? $o : array();
	$o['enabled'] = 'no';
	update_option( "woocommerce_{$g}_settings", $o );
}
delete_option( 'rtech_ai_order_request_done' );
update_option( 'woocommerce_checkout_phone_field', 'optional' );
update_option( 'woocommerce_ship_to_countries', 'disabled' );
$d = get_page_by_path( 'delivery-and-pickup' );
wp_update_post( array( 'ID' => $d->ID, 'post_status' => 'publish', 'post_content' => '<p>We do not deliver. You collect your order from our office.</p>' ) );
wp_insert_post( array( 'post_type' => 'page', 'post_title' => 'Shipping & Delivery Policy', 'post_name' => 'shipping-delivery-policy', 'post_status' => 'publish', 'post_content' => '<h2>2. Delivery target</h2><p>24-48 hours within Bengaluru.</p>' ) );
$privacy = (int) get_option( 'wp_page_for_privacy_policy' );
$grievance_block = '<h2>11. Grievance Officer</h2><p>raghavendra<br>Grievance Officer<br>Email: info@ramtechautomation.co.in</p>';
if ( $privacy ) {
	wp_update_post( array( 'ID' => $privacy, 'post_name' => 'privacy-policy', 'post_status' => 'publish', 'post_content' => '<p>Privacy Policy. Effective date: 7 September 2026.</p>' . $grievance_block ) );
} else {
	$privacy = wp_insert_post( array( 'post_type' => 'page', 'post_title' => 'Privacy Policy', 'post_name' => 'privacy-policy', 'post_status' => 'publish', 'post_content' => '<p>Privacy Policy.</p>' . $grievance_block ) );
	update_option( 'wp_page_for_privacy_policy', $privacy );
}
wp_insert_post( array( 'post_type' => 'page', 'post_title' => 'Customer Grievance', 'post_name' => 'customer-grievance', 'post_status' => 'publish', 'post_content' => '<p>Grievance Officer: raghavendra, Grievance Officer</p>' ) );
