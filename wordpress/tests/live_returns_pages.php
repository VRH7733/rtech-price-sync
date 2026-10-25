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
