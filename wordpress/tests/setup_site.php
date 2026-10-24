<?php
// Run with: wp eval-file setup_site.php
// Builds a tiny shop shaped like rtechelectricals.com: a priced cable, a Request a Quote MCB,
// category names stored with "&amp;" (as on the live site) and WooCommerce brands.
update_option( 'blogname', 'rtechelectricals' );
update_option( 'woocommerce_store_city', 'Bengaluru' );
update_option( 'woocommerce_store_postcode', '560065' );

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
