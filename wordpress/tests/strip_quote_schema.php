<?php
// Test-only mu-plugin: the live site prints no Product data for Request a Quote products.
// Copy that, so the plugin's fallback is exercised.
add_filter( 'woocommerce_structured_data_product', function ( $m, $product ) {
	return ( '' === (string) $product->get_price() ) ? array() : $m;
}, 10, 2 );
