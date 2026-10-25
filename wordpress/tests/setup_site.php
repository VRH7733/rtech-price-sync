<?php
// Run with: wp eval-file setup_site.php
// Builds a tiny shop shaped like rtechelectricals.com: a priced cable, a Request a Quote MCB,
// category names stored with "&amp;" (as on the live site) and WooCommerce brands.
update_option( 'blogname', 'rtechelectricals' );
update_option( 'woocommerce_store_city', 'Bengaluru' );
update_option( 'woocommerce_store_postcode', '560065' );
update_option( 'woocommerce_currency', 'INR' ); // as on the live shop

$cat = wp_insert_term( 'Wires &amp; Cables', 'product_cat', array( 'slug' => 'wires-cables' ) );
$cat_id = is_wp_error( $cat ) ? $cat->get_error_data() : $cat['term_id'];
$sw = wp_insert_term( 'Protection &amp; Switchgear', 'product_cat', array( 'slug' => 'protection-switchgear' ) );
$sw_id = is_wp_error( $sw ) ? $sw->get_error_data() : $sw['term_id'];
$brand = wp_insert_term( 'Havells', 'product_brand' );
$brand_id = is_wp_error( $brand ) ? $brand->get_error_data() : $brand['term_id'];

$p = new WC_Product_Simple();
$p->set_name( 'Havells Unarmoured 2XY LT Control Cable 61 Core 2.5 Sq.mm' );
$p->set_slug( 'priced-cable' );
$p->set_sku( 'RT-HAVE-2274' );
$p->set_regular_price( '13569' );
$p->set_short_description( '<ul class="rte-keyspecs"><li>Brand: Havells</li><li>Size: 2.5 sq mm</li><li>Cores: 61</li></ul><p>Prices include GST.</p>' );
$p->set_description( '<p>Havells Unarmoured 2XY LT Control Cable 61 Core 2.5 Sq.mm.</p>' );
$p->set_category_ids( array( $cat_id ) );
$p->set_status( 'publish' );
$id = $p->save();
wp_set_object_terms( $id, array( (int) $brand_id ), 'product_brand' );

$q = new WC_Product_External();
$q->set_name( 'Havells Crabtree 6A 1 Way Switch' );
$q->set_slug( 'quote-switch' );
$q->set_sku( 'RT-HAVE-0001' );
$q->set_regular_price( '' );
$q->set_button_text( 'Request a Quote' );
$q->set_product_url( home_url( '/contact/' ) );
$q->set_short_description( '<ul class="rte-keyspecs"><li>Brand: Havells</li><li>Current rating: 6 A</li></ul><p>Prices include GST.</p>' );
$q->set_category_ids( array( $sw_id ) );
$q->set_status( 'publish' );
$qid = $q->save();
wp_set_object_terms( $qid, array( (int) $brand_id ), 'product_brand' );

// Google feed (1.0.9): only products with a price and their own photo, and not hidden
function rtech_test_image( $name ) {
	$up   = wp_upload_dir();
	$file = $up['path'] . '/' . $name;
	// a 1x1 PNG is enough: the feed only needs the attachment's URL
	file_put_contents( $file, base64_decode( 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==' ) );
	return wp_insert_attachment( array( 'post_mime_type' => 'image/png', 'post_title' => $name, 'post_status' => 'inherit' ), $file );
}
$hw = wp_insert_term( 'House Wires', 'product_cat', array( 'slug' => 'house-wires', 'parent' => $cat_id ) );
$hw_id = is_wp_error( $hw ) ? $hw->get_error_data() : $hw['term_id'];
$w = new WC_Product_Simple();
$w->set_name( 'Havells Life Line Plus S3 HRFR 1.5 Sq.mm Wire 90 m & Red' );
$w->set_slug( 'feed-wire' );
$w->set_sku( 'RT-HAVE-0900' );
$w->set_regular_price( '1999' );
$w->set_sale_price( '1899' );
$w->set_stock_status( 'instock' );
$w->set_description( '<p>Havells Life Line Plus S3 HRFR wire, 1.5 sq mm, 90 m coil, red.</p>' );
$w->set_category_ids( array( $hw_id ) );
$w->set_image_id( rtech_test_image( 'feed-wire.png' ) );
$w->set_gallery_image_ids( array( rtech_test_image( 'feed-wire-2.png' ) ) );
$w->set_status( 'publish' );
$wid = $w->save();
wp_set_object_terms( $wid, array( (int) $brand_id ), 'product_brand' );

$n = new WC_Product_Simple();
$n->set_name( 'Havells 32A Double Pole MCB' );
$n->set_slug( 'no-photo-mcb' );
$n->set_sku( 'RT-HAVE-0901' );
$n->set_regular_price( '450' );
$n->set_category_ids( array( $sw_id ) );
$n->set_status( 'publish' );
$n->save();

$h = new WC_Product_Simple();
$h->set_name( 'Havells Hidden Test Product' );
$h->set_slug( 'hidden-item' );
$h->set_sku( 'RT-HAVE-0902' );
$h->set_regular_price( '300' );
$h->set_stock_status( 'outofstock' );
$h->set_catalog_visibility( 'hidden' );
$h->set_image_id( rtech_test_image( 'hidden.png' ) );
$h->set_category_ids( array( $sw_id ) );
$h->set_status( 'publish' );
$h->save();

// the live categories carry generic Rank Math text; the plugin replaces it (setting term_seo)
update_term_meta( $cat_id, 'rank_math_title', 'Wires & Cables Electrical Products' );
update_term_meta( $cat_id, 'rank_math_description', 'Browse Wires & Cables product families and request exact specifications.' );
update_option( 'rtech_ai_settings', array( 'profiles' => "https://www.facebook.com/rtech-test\nnot a link\nhttps://g.page/rtech-test" ) );

// the live sitemap lists pages and products only: category sitemap off, as there
$modules = (array) get_option( 'rank_math_modules', array() );
if ( ! in_array( 'sitemap', $modules, true ) ) {
	$modules[] = 'sitemap';
	update_option( 'rank_math_modules', $modules );
}
$sm = get_option( 'rank-math-options-sitemap' );
$sm = is_array( $sm ) ? $sm : array();
$sm['tax_product_cat_sitemap'] = 'off';
$sm['tax_product_brand_sitemap'] = 'off';
update_option( 'rank-math-options-sitemap', $sm );

$c = wp_insert_post( array( 'post_type' => 'page', 'post_title' => 'Contact Us', 'post_name' => 'contact-us', 'post_status' => 'publish',
	// as on the live site: the old .com address and a personal Gmail address (made up here)
	'post_content' => '<p>Email <a href="mailto:info@ramtechautomation.com">info@ramtechautomation.com</a> or Owner.Test99@gmail.com</p>' ) );
echo "priced=$id quote=$qid\n";
