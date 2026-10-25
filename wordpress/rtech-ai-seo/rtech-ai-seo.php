<?php
/**
 * Plugin Name:       RTech AI & Search Helper
 * Description:       Makes the shop easy for Google and AI assistants (ChatGPT, Gemini, Perplexity, Claude) to read: clean product descriptions, Product data on every product (Request a Quote ones too), one business name, readable breadcrumbs, a share image, and /llms.txt. Changes no prices, stock or product content.
 * Version:           1.0.7
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            RTechElectricals
 * License:           GPL-2.0-or-later
 *
 * Works alongside Rank Math and WooCommerce: it only rewrites what they output on the page.
 * Nothing is saved to products. Deactivating the plugin puts every page back as it was.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'RTECH_AI_VERSION', '1.0.7' );

/** Site-wide facts. Edit under Settings > RTech AI. */
function rtech_ai_settings() {
	$defaults = array(
		'brand_name' => 'RTechElectricals',
		'trade_name' => 'RAMTECH AUTOMATION',
		'city'       => 'Bengaluru',
		'email'      => 'info@ramtechautomation.co.in',
		'phone'      => '+91 84318 77469',
		// the shop address the site's own business data already shows (18 Oct 2026 audit)
		'street'     => 'Ground Floor, Building No. 904, 21st Cross, 16th Main, Judicial Layout, Allalasandra, near Yelahanka',
		'postcode'   => '560065',
		'region'     => 'Karnataka',
		'about'      => 'RTechElectricals is an electrical supplier in Bengaluru, Karnataka, India: wires and cables, modular switches, MCBs and switchgear, lighting, fans and pumps. Prices shown on the site include GST. Products without a listed price can be quoted on request.',
		'shop_desc'  => 'Shop 5,000+ electrical products in Bengaluru: Havells, Legrand, Polycab, KEI, RR Kabel and Finolex wires, cables, switches, MCBs, fans and lights. GST prices.',
		'home_desc'  => 'Authorised dealer in Bengaluru for Havells, Legrand, Polycab, KEI, RR Kabel and Finolex, and all other major brands on request. 5,000+ products, GST prices.',
		// "yes": category and brand pages get the "... in Bengaluru" title and description even where
		// one is saved in Rank Math (the live ones were generic: "Browse ... product families")
		'term_seo'   => 'yes',
		// the shop's pages elsewhere (Google Business Profile, Facebook, IndiaMART ...), one link per line
		'profiles'   => 'https://ramtechautomation.co.in/', // the company's own site (same business, same address)
		// "authorised dealer" is said only for these (Harshi, 16 Oct 2026); the others are "supplied on request"
		'dealer_brands' => 'Havells, Legrand, Polycab, KEI, RR Kabel, Finolex',
		'other_brands'  => 'Schneider Electric, Siemens, ABB, L&T, Anchor by Panasonic, Crompton, Bajaj, Philips, Wipro, Orient Electric, V-Guard, Syska, Hager',
		// "yes": a short "brands we supply" line above the footer on every page
		'brand_bar'     => 'yes',
		// addresses other plugins and pages still print; every page shows the business email instead
		'old_emails'    => 'info@ramtechautomation.com',
		// "yes": a Gmail address on a public page is replaced by the business email too
		'hide_gmail'    => 'yes',
		// India's e-commerce rules ask for the grievance officer's name and designation. The GST
		// proprietor, whose name the site's own business data already shows; contact = business only.
		'grievance'     => 'Kodandaram Kalavanchi, Proprietor',
		// made to order (Harshi, 24 Oct 2026); the types are filled in once Harshi lists them
		'panel_types'   => '',
		'tray_types'    => '',
	);
	$saved = get_option( 'rtech_ai_settings', array() );
	return wp_parse_args( is_array( $saved ) ? array_filter( $saved, 'strlen' ) : array(), $defaults );
}

/** The shop's own pages on other sites (Settings > RTech AI), as a list of links. */
function rtech_ai_profiles() {
	$links = preg_split( '/\s+/', (string) rtech_ai_settings()['profiles'], -1, PREG_SPLIT_NO_EMPTY );
	$links = array_filter(
		$links,
		function ( $l ) {
			return (bool) preg_match( '#^https?://[^/\s]+\.[^/\s]+#i', $l );
		}
	);
	return array_values( array_filter( array_map( 'esc_url_raw', $links ) ) );
}

/** "Havells, Legrand, ..." setting -> list of names. */
function rtech_ai_list( $text ) {
	return array_values( array_filter( array_map( 'trim', explode( ',', (string) $text ) ), 'strlen' ) );
}

/** "a, b and c" */
function rtech_ai_join( $items ) {
	$items = array_values( $items );
	if ( count( $items ) < 2 ) {
		return implode( '', $items );
	}
	$last = array_pop( $items );
	return implode( ', ', $items ) . ' and ' . $last;
}

/** The sentence that says which brands we supply: dealer brands, then every other major brand. */
function rtech_ai_supply_sentence() {
	$s      = rtech_ai_settings();
	$dealer = rtech_ai_list( $s['dealer_brands'] );
	$other  = rtech_ai_list( $s['other_brands'] );
	$text   = $dealer ? 'Authorised dealer for ' . rtech_ai_join( $dealer ) . '.' : '';
	$text  .= ' We also supply all other major electrical brands on request' . ( $other ? ', including ' . rtech_ai_join( $other ) : '' ) . '.';
	return trim( $text );
}

/** The about text plus the brands sentence (unless the saved about text already says it). */
function rtech_ai_about() {
	$about = rtech_ai_settings()['about'];
	return false !== stripos( $about, 'all other major' ) ? $about : $about . ' ' . rtech_ai_supply_sentence();
}

/** Repeatedly decode entities ("&amp;amp;" -> "&") and drop tags. */
function rtech_ai_plain( $text ) {
	$text = (string) $text;
	for ( $i = 0; $i < 3; $i++ ) {
		$decoded = html_entity_decode( $text, ENT_QUOTES | ENT_HTML5, 'UTF-8' );
		if ( $decoded === $text ) {
			break;
		}
		$text = $decoded;
	}
	// a list item or paragraph ends a phrase: keep a separator so "Brand: HavellsSize" cannot happen
	$text = preg_replace( '#</(li|p|h\d|tr|td|th|div)>#i', '$0; ', $text );
	$text = wp_strip_all_tags( $text );
	$text = preg_replace( '/\s*;\s*(;\s*)+/', '; ', $text );
	$text = preg_replace( '/\s+/', ' ', $text );
	return trim( $text, " ;\t\n" );
}

function rtech_ai_trim( $text, $max = 158 ) {
	if ( mb_strlen( $text ) <= $max ) {
		return $text;
	}
	$cut = mb_substr( $text, 0, $max - 1 );
	$space = mb_strrpos( $cut, ' ' );
	return rtrim( mb_substr( $cut, 0, $space ? $space : $max - 1 ), ' ,;.:' ) . '…';
}

/** "Brand: Havells; Size: 2.5 sq mm; Cores: 61" from the product's short description list. */
function rtech_ai_spec_phrase( $product ) {
	$short = $product->get_short_description();
	if ( ! preg_match_all( '#<li[^>]*>(.*?)</li>#is', $short, $m ) ) {
		return '';
	}
	$parts = array();
	foreach ( $m[1] as $li ) {
		$li = rtech_ai_plain( $li );
		if ( '' !== $li && 0 !== stripos( $li, 'Brand:' ) ) {
			$parts[] = $li;
		}
	}
	return implode( ', ', array_slice( $parts, 0, 4 ) );
}

function rtech_ai_brand( $product ) {
	foreach ( array( 'product_brand', 'pwb-brand', 'yith_product_brand' ) as $tax ) {
		if ( taxonomy_exists( $tax ) ) {
			$terms = get_the_terms( $product->get_id(), $tax );
			if ( $terms && ! is_wp_error( $terms ) ) {
				return rtech_ai_plain( $terms[0]->name );
			}
		}
	}
	return '';
}

function rtech_ai_category( $product ) {
	$terms = get_the_terms( $product->get_id(), 'product_cat' );
	if ( ! $terms || is_wp_error( $terms ) ) {
		return '';
	}
	foreach ( $terms as $t ) {
		if ( 'uncategorized' !== $t->slug ) {
			return rtech_ai_plain( $t->name );
		}
	}
	return '';
}

function rtech_ai_has_price( $product ) {
	return '' !== (string) $product->get_price() && (float) $product->get_price() > 0;
}

/** The sentence search results and AI answers show for a product. */
function rtech_ai_product_description( $product ) {
	$s     = rtech_ai_settings();
	$name  = rtech_ai_plain( $product->get_name() );
	$brand = rtech_ai_brand( $product );
	$specs = rtech_ai_spec_phrase( $product );
	$text  = $name . '.';
	if ( '' !== $specs ) {
		$text .= ' ' . $specs . '.';
	}
	$genuine = 'Genuine ' . ( $brand ? $brand . ' ' : '' ) . 'product';
	$text   .= rtech_ai_has_price( $product )
		? ' ' . $genuine . ', price incl. GST. Buy online at ' . $s['brand_name'] . ', ' . $s['city'] . '.'
		: ' ' . $genuine . '. Request a quote from ' . $s['brand_name'] . ', ' . $s['city'] . '.';
	return $text;
}

/** True when the page's own Rank Math description was typed by a person: never replace it. */
function rtech_ai_has_own_description( $post_id ) {
	return '' !== trim( (string) get_post_meta( $post_id, 'rank_math_description', true ) );
}

/** Product page that still has the generated "Brand: HavellsSize: ..." text. */
function rtech_ai_current_product() {
	if ( ! function_exists( 'is_product' ) || ! is_product() ) {
		return null;
	}
	$product = wc_get_product( get_queried_object_id() );
	return $product ? $product : null;
}

/* ---------- Meta description, Open Graph and title (Rank Math) ---------- */

function rtech_ai_filter_description( $description ) {
	$product = rtech_ai_current_product();
	if ( $product ) {
		return rtech_ai_has_own_description( $product->get_id() ) ? $description
			: rtech_ai_trim( rtech_ai_product_description( $product ) );
	}
	if ( is_front_page() ) {
		return rtech_ai_settings()['home_desc'];
	}
	if ( function_exists( 'is_shop' ) && is_shop() ) {
		return rtech_ai_settings()['shop_desc'];
	}
	$term = rtech_ai_current_term();
	if ( $term && rtech_ai_term_is_ours( $term, 'rank_math_description' ) ) {
		return rtech_ai_trim( 'product_brand' === $term->taxonomy ? rtech_ai_brand_description( $term ) : rtech_ai_category_description( $term ) );
	}
	return $description;
}

/** The product category or brand whose archive page this is. */
function rtech_ai_current_term() {
	if ( ! function_exists( 'is_product_category' ) || ! ( is_product_category() || is_tax( 'product_brand' ) ) ) {
		return null;
	}
	$term = get_queried_object();
	return ( $term instanceof WP_Term ) ? $term : null;
}

/** Whether the plugin writes this term's title or description ($meta: the Rank Math term meta key). */
function rtech_ai_term_is_ours( $term, $meta ) {
	return 'yes' === rtech_ai_settings()['term_seo'] || '' === trim( (string) get_term_meta( $term->term_id, $meta, true ) );
}

/** The top-level categories with the most products of a brand, cached for 12 hours. */
function rtech_ai_brand_categories( $term, $limit = 3 ) {
	global $wpdb;
	$key  = 'rtech_ai_brand_cats_' . $term->term_id;
	$cats = get_transient( $key );
	if ( is_array( $cats ) ) {
		return array_slice( $cats, 0, $limit );
	}
	$rows = $wpdb->get_results( $wpdb->prepare( "SELECT c.term_id, COUNT(DISTINCT r1.object_id) AS n FROM {$wpdb->term_relationships} r1 JOIN {$wpdb->term_taxonomy} b ON b.term_taxonomy_id = r1.term_taxonomy_id AND b.taxonomy = 'product_brand' AND b.term_id = %d JOIN {$wpdb->posts} p ON p.ID = r1.object_id AND p.post_status = 'publish' JOIN {$wpdb->term_relationships} r2 ON r2.object_id = r1.object_id JOIN {$wpdb->term_taxonomy} c ON c.term_taxonomy_id = r2.term_taxonomy_id AND c.taxonomy = 'product_cat' GROUP BY c.term_id", $term->term_id ) );
	$top = array();
	foreach ( (array) $rows as $r ) {
		$ancestors = get_ancestors( (int) $r->term_id, 'product_cat', 'taxonomy' );
		$root      = $ancestors ? (int) end( $ancestors ) : (int) $r->term_id;
		$top[ $root ] = ( isset( $top[ $root ] ) ? $top[ $root ] : 0 ) + (int) $r->n;
	}
	arsort( $top );
	$cats = array();
	foreach ( array_keys( $top ) as $id ) {
		$t = get_term( $id, 'product_cat' );
		if ( $t && ! is_wp_error( $t ) && 'uncategorized' !== $t->slug ) {
			$cats[] = rtech_ai_plain( $t->name );
		}
	}
	$cats = array_slice( $cats, 0, 6 );
	set_transient( $key, $cats, 12 * HOUR_IN_SECONDS );
	return array_slice( $cats, 0, $limit );
}

/** "Buy Havells in Bengaluru from RTechElectricals, authorised Havells dealer: 2,557 products ..." */
function rtech_ai_brand_description( $term ) {
	$s    = rtech_ai_settings();
	$name = rtech_ai_plain( $term->name );
	$cats = rtech_ai_brand_categories( $term );
	$text = 'Buy ' . $name . ' in ' . $s['city'] . ' from ' . $s['brand_name'] . ', authorised ' . $name . ' dealer: ' . number_format( (int) $term->count ) . ' products';
	if ( $cats ) {
		$last  = array_pop( $cats );
		$text .= ' including ' . ( $cats ? implode( ', ', $cats ) . ' and ' : '' ) . $last;
	}
	return $text . '. Prices include GST; order online or request a quote.';
}

/** "Wires & Cables in Bengaluru: Havells, KEI | RTechElectricals", "Havells Dealer in Bengaluru: Wires, Switches | ..." */
function rtech_ai_term_title( $term ) {
	$s    = rtech_ai_settings();
	$name = rtech_ai_plain( $term->name );
	if ( 'product_brand' === $term->taxonomy ) {
		$head = $name . ' Dealer in ' . $s['city'];
		$list = array_map(
			function ( $c ) {
				return trim( preg_split( '/\s+(?:&|and)\s+/', $c )[0] ); // "Wires & Cables" -> "Wires"
			},
			rtech_ai_brand_categories( $term )
		);
	} else {
		$head = $name . ' in ' . $s['city'];
		$list = array_slice( rtech_ai_category_brands( $term ), 0, 3 );
	}
	$tail = ' | ' . $s['brand_name'];
	for ( $n = count( $list ); $n > 0; $n-- ) {
		$title = $head . ': ' . implode( ', ', array_slice( $list, 0, $n ) ) . $tail;
		if ( mb_strlen( $title ) <= 65 ) {
			return $title;
		}
	}
	return $head . $tail;
}

/** The brands with the most products in a category (and its sub-categories), cached for 12 hours. */
function rtech_ai_category_brands( $term, $limit = 5 ) {
	global $wpdb;
	$key    = 'rtech_ai_cat_brands_' . $term->term_id;
	$brands = get_transient( $key );
	if ( is_array( $brands ) ) {
		return $brands;
	}
	$brands = array();
	if ( taxonomy_exists( 'product_brand' ) ) {
		$ids = array_map( 'intval', array_merge( array( $term->term_id ), (array) get_term_children( $term->term_id, 'product_cat' ) ) );
		$in  = implode( ',', $ids );
		// phpcs:ignore WordPress.DB.PreparedSQL -- $in is a list of integers
		$brands = $wpdb->get_col( $wpdb->prepare( "SELECT t.name FROM {$wpdb->term_relationships} r1 JOIN {$wpdb->term_taxonomy} c ON c.term_taxonomy_id = r1.term_taxonomy_id AND c.taxonomy = 'product_cat' AND c.term_id IN ($in) JOIN {$wpdb->posts} p ON p.ID = r1.object_id AND p.post_status = 'publish' JOIN {$wpdb->term_relationships} r2 ON r2.object_id = r1.object_id JOIN {$wpdb->term_taxonomy} b ON b.term_taxonomy_id = r2.term_taxonomy_id AND b.taxonomy = 'product_brand' JOIN {$wpdb->terms} t ON t.term_id = b.term_id GROUP BY t.term_id ORDER BY COUNT(DISTINCT r1.object_id) DESC LIMIT %d", $limit ) );
		$brands = array_map( 'rtech_ai_plain', (array) $brands );
	}
	set_transient( $key, $brands, 12 * HOUR_IN_SECONDS );
	return $brands;
}

/** "Buy Wires & Cables in Bengaluru from RTechElectricals: 2,506 products from Havells, KEI, ..." */
function rtech_ai_category_description( $term ) {
	$s      = rtech_ai_settings();
	$brands = rtech_ai_category_brands( $term );
	$count  = (int) $term->count;
	foreach ( (array) get_term_children( $term->term_id, 'product_cat' ) as $child ) {
		$c      = get_term( $child, 'product_cat' );
		$count += ( $c && ! is_wp_error( $c ) ) ? (int) $c->count : 0;
	}
	$text = 'Buy ' . rtech_ai_plain( $term->name ) . ' in ' . $s['city'] . ' from ' . $s['brand_name'] . ': ' . number_format( $count ) . ' products';
	if ( $brands ) {
		$text .= ' from ' . implode( ', ', $brands );
	}
	return $text . '. Prices include GST; order online or request a quote.';
}
add_filter( 'rank_math/frontend/description', 'rtech_ai_filter_description', 20 );
add_filter( 'rank_math/opengraph/facebook/og_description', 'rtech_ai_filter_description', 20 );
add_filter( 'rank_math/opengraph/twitter/twitter_description', 'rtech_ai_filter_description', 20 );

/** "Name - rtechelectricals" -> "Name | RTechElectricals" (the name the rest of the site uses). */
function rtech_ai_filter_title( $title ) {
	$term = rtech_ai_current_term();
	if ( $term && rtech_ai_term_is_ours( $term, 'rank_math_title' ) ) {
		return rtech_ai_term_title( $term );
	}
	$site = get_bloginfo( 'name' );
	$want = rtech_ai_settings()['brand_name'];
	if ( $site && $site !== $want ) {
		$title = preg_replace( '/\s+[-|–]\s+' . preg_quote( $site, '/' ) . '$/i', ' | ' . $want, $title );
	}
	return $title;
}
add_filter( 'rank_math/frontend/title', 'rtech_ai_filter_title', 20 );
add_filter( 'rank_math/opengraph/facebook/og_title', 'rtech_ai_filter_title', 20 );
add_filter( 'rank_math/opengraph/twitter/twitter_title', 'rtech_ai_filter_title', 20 );
add_filter(
	'rank_math/opengraph/facebook/og_site_name',
	function () {
		return rtech_ai_settings()['brand_name'];
	},
	20
);

/** A share image for pages that have none: the product photo if any, else the site logo. */
function rtech_ai_fallback_image_id() {
	$logo = (int) get_theme_mod( 'custom_logo' );
	if ( ! $logo && function_exists( 'blocksy_get_theme_mod' ) ) {
		$b = blocksy_get_theme_mod( 'custom_logo' );
		$logo = is_array( $b ) && isset( $b['desktop'] ) ? (int) $b['desktop'] : (int) $b;
	}
	return $logo ? $logo : (int) get_option( 'site_icon' );
}

add_action(
	'rank_math/opengraph/facebook/add_additional_images',
	function ( $image ) {
		if ( ! is_object( $image ) || ! method_exists( $image, 'has_images' ) || $image->has_images() ) {
			return;
		}
		$id = rtech_ai_fallback_image_id();
		if ( $id && method_exists( $image, 'add_image_by_id' ) ) {
			$image->add_image_by_id( $id );
		}
	}
);

/* ---------- Business name: one name everywhere ---------- */

add_filter(
	'rank_math/json_ld',
	function ( $data ) {
		$s = rtech_ai_settings();
		if ( isset( $data['WebSite'] ) && is_array( $data['WebSite'] ) ) {
			$data['WebSite']['name'] = $s['brand_name'];
		}
		if ( isset( $data['publisher'] ) && is_array( $data['publisher'] ) ) {
			$old = isset( $data['publisher']['name'] ) ? $data['publisher']['name'] : '';
			$data['publisher']['name'] = $s['brand_name'];
			if ( $old && strcasecmp( $old, $s['brand_name'] ) !== 0 ) {
				$data['publisher']['alternateName'] = $old;
			} elseif ( $s['trade_name'] ) {
				$data['publisher']['alternateName'] = $s['trade_name'];
			}
			$data['publisher']['url'] = home_url( '/' );
			$data['publisher']['description'] = rtech_ai_about();
			// a shop with an address is a local business: Google and AI answers use it for "in Bengaluru"
			if ( $s['street'] ) {
				$data['publisher']['@type']      = array( 'Organization', 'Store' );
				$data['publisher']['address']    = array(
					'@type'           => 'PostalAddress',
					'streetAddress'   => $s['street'],
					'addressLocality' => $s['city'],
					'addressRegion'   => $s['region'],
					'postalCode'      => $s['postcode'],
					'addressCountry'  => 'IN',
				);
				$data['publisher']['areaServed'] = array( $s['city'], $s['region'] );
			}
			if ( $s['phone'] ) {
				$data['publisher']['telephone'] = preg_replace( '/[^\d+]/', '', $s['phone'] );
			}
			if ( $s['email'] ) {
				$data['publisher']['email'] = $s['email'];
			}
			if ( rtech_ai_services_page() ) {
				$url  = get_permalink( rtech_ai_services_page() );
				$area = array( '@type' => 'City', 'name' => $s['city'] );
				$data['publisher']['hasOfferCatalog'] = array(
					'@type'           => 'OfferCatalog',
					'name'            => 'Made to order',
					'itemListElement' => array(
						array( '@type' => 'Offer', 'itemOffered' => array( '@type' => 'Service', 'name' => 'Custom electrical panel boards', 'url' => $url, 'areaServed' => $area ) ),
						array( '@type' => 'Offer', 'itemOffered' => array( '@type' => 'Service', 'name' => 'Cable trays made to size', 'url' => $url, 'areaServed' => $area ) ),
					),
				);
			}
			if ( rtech_ai_profiles() ) {
				$data['publisher']['sameAs'] = rtech_ai_profiles();
			}
		}
		return $data;
	},
	99
);

/* ---------- WooCommerce structured data ---------- */

/**
 * Text for JSON-LD. WooCommerce HTML-escapes its JSON-LD on output, so a "&" reaches Google and AI
 * readers as the literal text "&amp;" (on the live site even "&amp;amp;"): write "and" instead.
 */
function rtech_ai_ld_text( $text ) {
	return trim( preg_replace( '/\s*&\s*/', ' and ', rtech_ai_plain( $text ) ) );
}

/** One Product node: name, sku, brand, category, clean description, image, offer details. */
function rtech_ai_product_markup( $markup, $product ) {
	if ( ! is_array( $markup ) || ! $product ) {
		return $markup;
	}
	$s = rtech_ai_settings();
	$markup['name']        = rtech_ai_ld_text( $product->get_name() );
	$markup['description'] = rtech_ai_ld_text( rtech_ai_product_description( $product ) );
	$brand = rtech_ai_brand( $product );
	if ( $brand && empty( $markup['brand'] ) ) {
		$markup['brand'] = array( '@type' => 'Brand', 'name' => rtech_ai_ld_text( $brand ) );
	}
	$cat = rtech_ai_category( $product );
	if ( $cat ) {
		$markup['category'] = rtech_ai_ld_text( $cat );
	}
	if ( ! empty( $markup['offers'] ) && is_array( $markup['offers'] ) ) {
		foreach ( $markup['offers'] as $i => $offer ) {
			if ( ! is_array( $offer ) ) {
				continue;
			}
			$offer['itemCondition'] = 'https://schema.org/NewCondition';
			$offer['seller']        = array(
				'@type' => 'Organization',
				'name'  => $s['brand_name'],
				'url'   => home_url( '/' ),
			);
			$markup['offers'][ $i ] = $offer;
		}
	}
	return $markup;
}

$GLOBALS['rtech_ai_product_seen'] = false;
add_filter(
	'woocommerce_structured_data_product',
	function ( $markup, $product ) {
		if ( is_array( $markup ) && ! empty( $markup['@type'] ) && $product && $product->get_id() === get_queried_object_id() ) {
			$GLOBALS['rtech_ai_product_seen'] = true;
		}
		return rtech_ai_product_markup( $markup, $product );
	},
	99,
	2
);

/** The same for the Product that Rank Math prints when its WooCommerce schema is switched on. */
add_filter(
	'rank_math/snippet/rich_snippet_product_entity',
	function ( $entity ) {
		$product = rtech_ai_current_product();
		if ( ! $product || ! is_array( $entity ) ) {
			return $entity;
		}
		if ( isset( $entity['offers'] ) && is_array( $entity['offers'] ) && isset( $entity['offers']['@type'] ) ) {
			$entity['offers'] = array( $entity['offers'] ); // one offer object -> list, as WooCommerce writes it
			$entity = rtech_ai_product_markup( $entity, $product );
			$entity['offers'] = $entity['offers'][0];
		} else {
			$entity = rtech_ai_product_markup( $entity, $product );
		}
		$GLOBALS['rtech_ai_product_seen'] = true;
		return $entity;
	},
	99
);

/** Breadcrumbs: "Wires &amp;amp; Cables" -> "Wires and Cables". */
add_filter(
	'woocommerce_structured_data_breadcrumblist',
	function ( $markup ) {
		if ( ! empty( $markup['itemListElement'] ) && is_array( $markup['itemListElement'] ) ) {
			foreach ( $markup['itemListElement'] as $i => $el ) {
				if ( isset( $el['item']['name'] ) ) {
					$markup['itemListElement'][ $i ]['item']['name'] = rtech_ai_ld_text( $el['item']['name'] );
				}
			}
		}
		return $markup;
	},
	99
);

/**
 * Request a Quote products: WooCommerce leaves them without any Product data, so search engines
 * and AI assistants cannot tell the brand or model. Add the Product (no price, no offer: there is
 * no price to state) just before WooCommerce prints its data in the footer.
 */
add_action(
	'wp_footer',
	function () {
		$product = rtech_ai_current_product();
		if ( ! $product || ! empty( $GLOBALS['rtech_ai_product_seen'] ) || ! function_exists( 'WC' ) || ! WC()->structured_data ) {
			return;
		}
		foreach ( (array) WC()->structured_data->get_data() as $node ) {
			if ( is_array( $node ) && isset( $node['@type'] ) && 'Product' === $node['@type'] ) {
				return;
			}
		}
		$permalink = get_permalink( $product->get_id() );
		$markup    = array(
			'@type' => 'Product',
			'@id'   => $permalink . '#product',
			'name'  => $product->get_name(),
			'url'   => $permalink,
			'sku'   => $product->get_sku() ? $product->get_sku() : (string) $product->get_id(),
		);
		$img = wp_get_attachment_url( $product->get_image_id() );
		if ( $img ) {
			$markup['image'] = $img;
		}
		WC()->structured_data->set_data( rtech_ai_product_markup( $markup, $product ) );
	},
	5
);

/* ---------- /llms.txt ---------- */

function rtech_ai_llms_txt() {
	$cached = get_transient( 'rtech_ai_llms_txt' );
	if ( is_string( $cached ) && '' !== $cached ) {
		return $cached;
	}
	$s     = rtech_ai_settings();
	$lines = array( '# ' . $s['brand_name'], '', '> ' . rtech_ai_about(), '' );

	$facts = array( '- Website: ' . home_url( '/' ) );
	if ( $s['trade_name'] ) {
		$facts[] = '- Business: ' . $s['brand_name'] . ' (' . $s['trade_name'] . '), ' . $s['city'] . ', India';
	}
	$addr = array_filter(
		array(
			get_option( 'woocommerce_store_address' ),
			get_option( 'woocommerce_store_address_2' ),
			get_option( 'woocommerce_store_city' ),
			get_option( 'woocommerce_store_postcode' ),
		)
	);
	if ( ! get_option( 'woocommerce_store_address' ) && $s['street'] ) {
		$addr = array( $s['street'], $s['city'], $s['region'] . ' ' . $s['postcode'], 'India' );
	}
	if ( $addr ) {
		$facts[] = '- Address: ' . implode( ', ', array_filter( $addr ) );
	}
	$facts[] = '- Serves: ' . $s['city'] . ' and ' . $s['region'];
	if ( $s['phone'] ) {
		$facts[] = '- Phone: ' . $s['phone'];
	}
	if ( $s['email'] ) {
		$facts[] = '- Email: ' . $s['email'];
	}
	if ( rtech_ai_list( $s['dealer_brands'] ) ) {
		$facts[] = '- Authorised dealer for: ' . implode( ', ', rtech_ai_list( $s['dealer_brands'] ) );
	}
	$facts[] = '- Also supplies all other major electrical brands on request' . ( rtech_ai_list( $s['other_brands'] ) ? ': ' . implode( ', ', rtech_ai_list( $s['other_brands'] ) ) . ' and more' : '' );
	foreach ( rtech_ai_profiles() as $link ) {
		$facts[] = '- Also on: ' . $link;
	}
	$facts[] = '- Prices include GST; products with a price can be ordered online (add to cart).';
	$facts[] = '- Delivery: collect from the office or send your own transport (courier, Porter, own vehicle); we load it at no charge.';
	if ( rtech_ai_services_page() ) {
		$facts[] = '- Also builds to order: custom electrical panel boards and cable trays (' . get_permalink( rtech_ai_services_page() ) . ')';
	}
	$facts[] = '- Products without a price show "Request a Quote": send the product and quantity and we reply with a price.';
	$lines   = array_merge( $lines, $facts, array( '' ) );

	if ( function_exists( 'wc_get_page_permalink' ) ) {
		$counts  = wp_count_posts( 'product' );
		$lines[] = '## Shop';
		$lines[] = '';
		$lines[] = '- [All products](' . wc_get_page_permalink( 'shop' ) . '): ' . (int) $counts->publish . ' electrical products';
		$lines[] = '';
	}

	$cats = get_terms( array( 'taxonomy' => 'product_cat', 'hide_empty' => true, 'parent' => 0, 'orderby' => 'count', 'order' => 'DESC' ) );
	if ( $cats && ! is_wp_error( $cats ) ) {
		$lines[] = '## Product categories';
		$lines[] = '';
		foreach ( $cats as $c ) {
			if ( 'uncategorized' === $c->slug ) {
				continue;
			}
			$line = '- [' . rtech_ai_plain( $c->name ) . '](' . get_term_link( $c ) . '): ' . (int) $c->count . ' products';
			$kids = get_terms( array( 'taxonomy' => 'product_cat', 'hide_empty' => true, 'parent' => $c->term_id, 'orderby' => 'count', 'order' => 'DESC', 'number' => 12 ) );
			if ( $kids && ! is_wp_error( $kids ) ) {
				$line .= ', including ' . implode( ', ', array_map( function ( $k ) { return rtech_ai_plain( $k->name ); }, $kids ) );
			}
			$lines[] = $line;
		}
		$lines[] = '';
	}

	if ( taxonomy_exists( 'product_brand' ) ) {
		$brands = get_terms( array( 'taxonomy' => 'product_brand', 'hide_empty' => true, 'orderby' => 'count', 'order' => 'DESC' ) );
		if ( $brands && ! is_wp_error( $brands ) ) {
			$lines[] = '## Brands';
			$lines[] = '';
			foreach ( $brands as $b ) {
				$lines[] = '- [' . rtech_ai_plain( $b->name ) . '](' . get_term_link( $b ) . '): ' . (int) $b->count . ' products';
			}
			$lines[] = '';
		}
	}

	$pages = array();
	foreach ( array( 'about', 'about-us', 'contact', 'contact-us', 'shipping', 'shipping-policy', 'delivery', 'refund', 'refund-policy', 'returns', 'return-policy', 'refund_returns', 'terms', 'terms-and-conditions', 'faq', 'faqs', 'brands-we-supply', 'custom-panel-boards-cable-trays', 'delivery-and-pickup', 'return-cancellation-policy', 'returns-and-refunds', 'upload-boq', 'bulk-order', 'request-a-quote' ) as $slug ) {
		$p = get_page_by_path( $slug );
		if ( $p && 'publish' === $p->post_status ) {
			$pages[ $p->ID ] = '- [' . rtech_ai_plain( get_the_title( $p ) ) . '](' . get_permalink( $p ) . ')';
		}
	}
	$privacy = (int) get_option( 'wp_page_for_privacy_policy' );
	if ( $privacy && 'publish' === get_post_status( $privacy ) ) {
		$pages[ $privacy ] = '- [' . rtech_ai_plain( get_the_title( $privacy ) ) . '](' . get_permalink( $privacy ) . ')';
	}
	if ( $pages ) {
		$lines[] = '## About, ordering and policies';
		$lines[] = '';
		$lines   = array_merge( $lines, array_values( $pages ), array( '' ) );
	}

	$lines[] = '## Optional';
	$lines[] = '';
	$lines[] = '- [Sitemap of every product page](' . home_url( '/sitemap_index.xml' ) . ')';
	$lines[] = '';

	$text = implode( "\n", $lines );
	set_transient( 'rtech_ai_llms_txt', $text, 12 * HOUR_IN_SECONDS );
	return $text;
}

add_action(
	'parse_request',
	function () {
		$path = wp_parse_url( isset( $_SERVER['REQUEST_URI'] ) ? wp_unslash( $_SERVER['REQUEST_URI'] ) : '', PHP_URL_PATH ); // phpcs:ignore WordPress.Security.ValidatedSanitizedInput
		$home = rtrim( (string) wp_parse_url( home_url( '/' ), PHP_URL_PATH ), '/' );
		if ( $path !== $home . '/llms.txt' ) {
			return;
		}
		status_header( 200 );
		header( 'Content-Type: text/plain; charset=utf-8' );
		header( 'X-Robots-Tag: noindex' );
		header( 'Cache-Control: public, max-age=43200' );
		echo rtech_ai_llms_txt(); // phpcs:ignore WordPress.Security.EscapeOutput -- plain text
		exit;
	},
	0
);

/** Rebuild llms.txt after products or categories change (at most every 12 hours otherwise). */
foreach ( array( 'created_product_cat', 'edited_product_cat', 'delete_product_cat', 'created_product_brand', 'edited_product_brand', 'update_option_rtech_ai_settings' ) as $hook ) {
	add_action( $hook, function () { delete_transient( 'rtech_ai_llms_txt' ); } );
}

/* ---------- "Brands we supply" line on every page ---------- */

/** Page to send "can't find it?" visitors to: the BOQ upload page, else the contact page. */
function rtech_ai_enquiry_url() {
	foreach ( array( 'upload-boq', 'request-a-quote', 'contact', 'contact-us' ) as $slug ) {
		$p = get_page_by_path( $slug );
		if ( $p && 'publish' === $p->post_status ) {
			return get_permalink( $p );
		}
	}
	return home_url( '/' );
}

/** The dealer brands as links to their brand pages (where one exists). */
function rtech_ai_brand_links_html( $names ) {
	$out = array();
	foreach ( $names as $name ) {
		$term = taxonomy_exists( 'product_brand' ) ? get_term_by( 'name', $name, 'product_brand' ) : null;
		$link = $term ? get_term_link( $term ) : '';
		$out[] = ( $link && ! is_wp_error( $link ) ) ? '<a href="' . esc_url( $link ) . '">' . esc_html( $name ) . '</a>' : esc_html( $name );
	}
	return rtech_ai_join( $out );
}

function rtech_ai_brand_bar_html() {
	$s      = rtech_ai_settings();
	$dealer = rtech_ai_list( $s['dealer_brands'] );
	$other  = rtech_ai_list( $s['other_brands'] );
	$phone  = preg_replace( '/[^\d+]/', '', $s['phone'] );
	$html   = '<section class="rtech-brands-bar" aria-label="Brands we supply" style="max-width:1200px;margin:32px auto 0;padding:16px 20px;border-top:1px solid rgba(0,0,0,.1);font-size:15px;line-height:1.6;text-align:center">';
	$html  .= '<p style="margin:0">';
	if ( $dealer ) {
		$html .= '<strong>Authorised dealer for ' . rtech_ai_brand_links_html( $dealer ) . '.</strong> ';
	}
	$html .= 'We also supply all other major electrical brands' . ( $other ? ', including ' . esc_html( rtech_ai_join( $other ) ) : '' ) . '. ';
	if ( rtech_ai_services_page() ) {
		$html .= 'We also build <a href="' . esc_url( get_permalink( rtech_ai_services_page() ) ) . '">custom panel boards and cable trays</a>. ';
	}
	$html .= 'Can\'t find a product? ';
	if ( $phone ) {
		$html .= 'Call <a href="tel:' . esc_attr( $phone ) . '">' . esc_html( $s['phone'] ) . '</a> or ';
	}
	$html .= '<a href="' . esc_url( rtech_ai_enquiry_url() ) . '">send us your list</a> for a quote.</p></section>';
	return $html;
}

function rtech_ai_print_brand_bar() {
	if ( ! empty( $GLOBALS['rtech_ai_bar_done'] ) || is_admin() || is_feed() || 'yes' !== rtech_ai_settings()['brand_bar'] ) {
		return;
	}
	$GLOBALS['rtech_ai_bar_done'] = true;
	echo rtech_ai_brand_bar_html(); // phpcs:ignore WordPress.Security.EscapeOutput -- escaped above
}
add_action( 'blocksy:footer:before', 'rtech_ai_print_brand_bar' ); // the live theme: just above the footer
add_action( 'wp_footer', 'rtech_ai_print_brand_bar', 1 );         // any other theme

/* ---------- After an update: fresh llms.txt, a draft brands page, a cache purge ---------- */

/** "Brands we supply" page text: every brand in the shop with its product count, then the others. */
function rtech_ai_brands_page_html() {
	$s     = rtech_ai_settings();
	$html  = '<p><strong>' . esc_html( $s['brand_name'] ) . ', ' . esc_html( $s['city'] ) . '.</strong> ' . esc_html( rtech_ai_supply_sentence() ) . ' Prices on the site include GST.</p>';
	$terms = taxonomy_exists( 'product_brand' ) ? get_terms( array( 'taxonomy' => 'product_brand', 'hide_empty' => true, 'orderby' => 'count', 'order' => 'DESC' ) ) : array();
	if ( $terms && ! is_wp_error( $terms ) ) {
		$html .= '<h2>Brands in our online shop</h2><ul>';
		foreach ( $terms as $t ) {
			$html .= '<li><a href="' . esc_url( get_term_link( $t ) ) . '">' . esc_html( rtech_ai_plain( $t->name ) ) . '</a>: ' . number_format( (int) $t->count ) . ' products</li>';
		}
		$html .= '</ul>';
	}
	if ( rtech_ai_list( $s['other_brands'] ) ) {
		$html .= '<h2>Other brands we supply on request</h2><p>' . esc_html( rtech_ai_join( rtech_ai_list( $s['other_brands'] ) ) ) . ', and any other major electrical brand.</p>';
	}
	$html .= '<h2>How to order</h2><p>Products with a price can be ordered online. For anything else, call ' . esc_html( $s['phone'] ) . ', email ' . esc_html( $s['email'] ) . ' or <a href="' . esc_url( rtech_ai_enquiry_url() ) . '">send us your list</a> and we reply with a quote.</p>';
	return $html;
}

/** The published "Custom Panel Boards and Cable Trays" page, or null while it is a draft. */
function rtech_ai_services_page() {
	$p = get_page_by_path( 'custom-panel-boards-cable-trays' );
	return ( $p && 'publish' === $p->post_status ) ? $p : null;
}

/** Made-to-order work, as a page: what we build, and how to ask for a quote. */
function rtech_ai_services_page_html() {
	$s      = rtech_ai_settings();
	$panels = rtech_ai_list( $s['panel_types'] );
	$trays  = rtech_ai_list( $s['tray_types'] );
	$who    = $s['trade_name'] ? $s['trade_name'] . ' (' . $s['brand_name'] . ')' : $s['brand_name'];
	$h  = '<p>' . esc_html( $who ) . ' builds custom electrical panel boards and cable trays in ' . esc_html( $s['city'] ) . ', made to your drawing, load list or site needs.</p>';
	$h .= '<h2>Custom panel boards</h2><p>' . ( $panels ? 'We build ' . esc_html( rtech_ai_join( $panels ) ) . '. ' : '' );
	$h .= 'Each panel is built to your single-line diagram or requirement, with the switchgear brand you choose. We supply ' . esc_html( rtech_ai_join( rtech_ai_list( $s['dealer_brands'] ) ) ) . ' and all other major brands.</p>';
	$h .= '<h2>Cable trays</h2><p>' . ( $trays ? 'We make ' . esc_html( rtech_ai_join( $trays ) ) . '. ' : '' ) . 'Made to the sizes and lengths your site needs.</p>';
	$h .= '<h2>Get a quote</h2><p>Send your drawing, single-line diagram or list of requirements. <a href="' . esc_url( rtech_ai_enquiry_url() ) . '">Upload it here</a>, or contact us: ' . rtech_ai_contact_html() . '. Address: ' . esc_html( rtech_ai_address_line() ) . '.</p>';
	return $h;
}

/** The shop's address on one line, from the settings. */
function rtech_ai_address_line() {
	$s = rtech_ai_settings();
	return implode( ', ', array_filter( array( $s['street'], $s['city'], $s['region'] . ' ' . $s['postcode'] ) ) );
}

/** How to reach us, for the policy pages. */
function rtech_ai_contact_html() {
	$s     = rtech_ai_settings();
	$phone = preg_replace( '/[^\d+]/', '', $s['phone'] );
	return 'Phone or WhatsApp <a href="tel:' . esc_attr( $phone ) . '">' . esc_html( $s['phone'] ) . '</a>, email <a href="mailto:' . esc_attr( $s['email'] ) . '">' . esc_html( $s['email'] ) . '</a>';
}

/** Delivery terms as Harshi set them on 24 Oct 2026: pickup or the customer's own transport, we load. */
function rtech_ai_delivery_page_html() {
	$s = rtech_ai_settings();
	$h = '<p>We do not deliver. You collect your order from our office, or send your own transport, and we load it for you at no charge.</p>';
	$h .= '<h2>1. Collect from our office</h2><p>' . esc_html( rtech_ai_address_line() ) . '. Please call before you come, so your order is packed and ready.</p>';
	$h .= '<h2>2. Send your own transport</h2><p>Send your own vehicle, a courier, Porter or any transporter of your choice. We load the goods onto your vehicle or hand them to your courier at our office. The transport cost and the booking are yours.</p>';
	$h .= '<h2>Check your goods at loading</h2><p>Please check the quantity, the model and the condition of the goods when they are loaded or handed over, and sign the delivery note. From that moment the goods travel at the buyer\'s risk: we are not responsible for loss or damage in transit.</p>';
	$h .= '<h2>Invoice</h2><p>Every order comes with a GST invoice. Prices on the website include GST.</p>';
	$h .= '<h2>Questions</h2><p>' . rtech_ai_contact_html() . '.</p>';
	return $h;
}

/** Return and refund terms as Harshi set them on 24 Oct 2026, with the usual dealer terms around them. */
function rtech_ai_returns_page_html() {
	$s = rtech_ai_settings();
	$h = '<h2>Wrong or faulty item</h2><p>If you receive a wrong item or a faulty one, tell us within 7 days of collection. Send the invoice number and photos or a short video of the problem to ' . rtech_ai_contact_html() . '.</p>';
	$h .= '<h2>Replacement</h2><ul><li>We replace a wrong or faulty item once, and we arrange the transport for that replacement.</li><li>If the replacement also has a problem, you can collect another replacement from our office, or ask for a refund.</li></ul>';
	$h .= '<h2>Refund</h2><p>Refunds are paid to the original payment method within 7 business days after we receive and check the returned item.</p>';
	$h .= '<h2>What we cannot take back</h2><ul><li>Wires and cables cut to the length you ordered</li><li>Items that have been installed or used</li><li>Items damaged by wrong installation, wrong voltage or rough handling</li><li>Items ordered specially for you</li><li>Items returned without the original box and invoice</li><li>Items you no longer want, if there is nothing wrong with them</li></ul>';
	$delivery = get_page_by_path( 'delivery-and-pickup' );
	$h       .= '<h2>Delivery</h2><p>We do not deliver. You collect your order from our office, or send your own vehicle, courier or Porter, and we load it for you at no charge. Please check the goods at loading; after that they travel at the buyer\'s risk.' . ( ( $delivery && 'publish' === $delivery->post_status ) ? ' <a href="' . esc_url( get_permalink( $delivery ) ) . '">Delivery and pickup details</a>.' : '' ) . '</p>';
	$h .= '<h2>Cancelling an order</h2><p>You can cancel an order before the goods are loaded or handed over. We refund the full amount within 7 business days.</p>';
	$h .= '<h2>Manufacturer\'s warranty</h2><p>Products carry the brand\'s own warranty. Warranty claims are handled under the brand\'s warranty terms; we help you with the invoice and the claim.</p>';
	$who = trim( $s['grievance'] . ', ' . ( $s['trade_name'] ? $s['trade_name'] : $s['brand_name'] ), ', ' );
	$h  .= '<h2>Grievance officer</h2><p>' . esc_html( $who ) . ', ' . esc_html( rtech_ai_address_line() ) . '. ' . rtech_ai_contact_html() . '. We acknowledge every complaint within 48 hours and resolve it within one month.</p>';
	return $h;
}

/**
 * One returns page (Harshi, 25 Oct 2026: "make a plugin so you do it all"). The site had three:
 * WooCommerce's sample "Refund and Returns Policy" (published by mistake, says 30 days), the shop's
 * own "Return & Cancellation Policy" (live since 7 Sep), and the plugin's "Returns and Refunds" draft.
 * Keep the own page's address and put the owner's terms in it; move the other two to Trash.
 * Everything here can be undone: Trash keeps pages 30 days, the old text is kept as a revision and
 * in the option rtech_ai_returns_backup. Runs once.
 */
function rtech_ai_one_returns_page() {
	if ( get_option( 'rtech_ai_returns_done' ) ) {
		return;
	}
	$own = get_page_by_path( 'return-cancellation-policy' );
	if ( ! $own || 'publish' !== $own->post_status ) {
		rtech_ai_add_draft_page( 'returns-and-refunds', 'Returns and Refunds', rtech_ai_returns_page_html() );
		return; // no page of the shop's own to fill: leave the draft for the owner, as before
	}
	update_option( 'rtech_ai_returns_done', time() );
	update_option( 'rtech_ai_returns_backup', array( 'ID' => $own->ID, 'content' => $own->post_content, 'saved' => time() ), false );
	wp_update_post( array( 'ID' => $own->ID, 'post_content' => rtech_ai_returns_page_html() ) );

	$sample = get_page_by_path( 'refund_returns' );
	// only WooCommerce's untouched sample text, never a page someone wrote
	if ( $sample && false !== stripos( $sample->post_content, 'This is a sample page' ) ) {
		wp_trash_post( $sample->ID );
	}
	$draft = get_page_by_path( 'returns-and-refunds' );
	if ( $draft && 'draft' === $draft->post_status ) {
		wp_trash_post( $draft->ID );
	}
}

/** New site content goes in as a DRAFT: the owner reads and publishes it. Never touches an existing page. */
function rtech_ai_add_draft_page( $slug, $title, $html ) {
	if ( get_page_by_path( $slug ) ) {
		return;
	}
	wp_insert_post(
		array(
			'post_type'    => 'page',
			'post_status'  => 'draft',
			'post_title'   => $title,
			'post_name'    => $slug,
			'post_content' => $html,
		)
	);
}

add_action(
	'init',
	function () {
		if ( get_option( 'rtech_ai_version' ) === RTECH_AI_VERSION ) {
			return;
		}
		update_option( 'rtech_ai_version', RTECH_AI_VERSION ); // first, so two requests cannot both run this
		delete_transient( 'rtech_ai_llms_txt' );
		rtech_ai_add_draft_page( 'brands-we-supply', 'Brands We Supply', rtech_ai_brands_page_html() );
		rtech_ai_add_draft_page( 'delivery-and-pickup', 'Delivery and Pickup', rtech_ai_delivery_page_html() );
		rtech_ai_one_returns_page();
		rtech_ai_add_draft_page( 'custom-panel-boards-cable-trays', 'Custom Panel Boards and Cable Trays in Bengaluru', rtech_ai_services_page_html() );
		do_action( 'litespeed_purge_all' ); // LiteSpeed Cache's own "Purge All"; nothing happens without it
	},
	20
);

/* ---------- One business email on every page ---------- */

/** Swap the old addresses (and any Gmail address) for the business email in a page's HTML. */
function rtech_ai_fix_emails( $html ) {
	$s    = rtech_ai_settings();
	$want = sanitize_email( $s['email'] );
	if ( ! $want || ! is_string( $html ) || '' === $html ) {
		return $html;
	}
	foreach ( rtech_ai_list( $s['old_emails'] ) as $old ) {
		if ( is_email( $old ) && strcasecmp( $old, $want ) !== 0 ) {
			$html = str_ireplace( $old, $want, $html );
		}
	}
	if ( 'yes' === $s['hide_gmail'] ) {
		$html = preg_replace( '/(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@(?:gmail|googlemail)\.com\b/i', $want, $html );
	}
	return $html;
}

add_action(
	'template_redirect',
	function () {
		if ( is_admin() || is_feed() || wp_doing_ajax() || ( defined( 'REST_REQUEST' ) && REST_REQUEST ) ) {
			return;
		}
		ob_start( 'rtech_ai_fix_emails' );
	},
	0
);

/* ---------- Sitemap: category and brand pages too ---------- */

/**
 * Rank Math's sitemap on the live site lists pages and products only, so Google finds the
 * category and brand pages ("Havells", "Wires & Cables": the pages that answer "Havells wire
 * Bengaluru") only through links. Switch both taxonomies' sitemaps on while the plugin is active.
 */
add_filter(
	'option_rank-math-options-sitemap',
	function ( $opts ) {
		if ( is_array( $opts ) ) {
			foreach ( array( 'product_cat', 'product_brand' ) as $tax ) {
				$opts[ 'tax_' . $tax . '_sitemap' ] = 'on';
			}
		}
		return $opts;
	},
	20
);

/* ---------- Robots: keep site search results out of the index ---------- */

add_filter(
	'rank_math/frontend/robots',
	function ( $robots ) {
		if ( is_search() ) {
			$robots['index'] = 'noindex';
			$robots['follow'] = 'follow';
		}
		return $robots;
	},
	20
);

/* ---------- Settings > RTech AI ---------- */

add_action(
	'admin_menu',
	function () {
		add_options_page( 'RTech AI', 'RTech AI', 'manage_options', 'rtech-ai', 'rtech_ai_settings_page' );
	}
);

add_action(
	'admin_init',
	function () {
		register_setting(
			'rtech_ai',
			'rtech_ai_settings',
			array(
				'type'              => 'array',
				'sanitize_callback' => function ( $in ) {
					$out = array();
					foreach ( array( 'brand_name', 'trade_name', 'street', 'city', 'region', 'postcode', 'email', 'phone', 'home_desc', 'shop_desc', 'about', 'profiles', 'dealer_brands', 'other_brands', 'old_emails', 'grievance', 'panel_types', 'tray_types' ) as $k ) {
						$out[ $k ] = isset( $in[ $k ] ) ? sanitize_textarea_field( $in[ $k ] ) : '';
					}
					$out['email']    = sanitize_email( $out['email'] );
					$out['term_seo'] = empty( $in['term_seo'] ) ? 'no' : 'yes';
					$out['brand_bar'] = empty( $in['brand_bar'] ) ? 'no' : 'yes';
					$out['hide_gmail'] = empty( $in['hide_gmail'] ) ? 'no' : 'yes';
					return $out;
				},
			)
		);
	}
);

function rtech_ai_settings_page() {
	$s      = rtech_ai_settings();
	$fields = array(
		'brand_name' => 'Shop name shown to Google and AI',
		'trade_name' => 'Registered trade name',
		'street'     => 'Shop street address',
		'city'       => 'City',
		'region'     => 'State',
		'postcode'   => 'PIN code',
		'email'      => 'Customer email (shown in /llms.txt)',
		'phone'      => 'Customer phone (shown in /llms.txt and the business data)',
		'home_desc'  => 'Home page description (Google shows about 155 characters)',
		'shop_desc'  => 'Shop page description',
		'about'      => 'About the business (top of /llms.txt and the business data)',
		'profiles'   => 'The shop on other sites: Google Business Profile, Facebook, IndiaMART ... (one link per line)',
		'dealer_brands' => 'Brands you are an authorised dealer for (comma separated)',
		'other_brands'  => 'Other brands you supply on request (comma separated)',
		'brand_bar'     => 'Show the "brands we supply" line above the footer on every page',
		'old_emails'    => 'Old email addresses to replace with the customer email on every page (comma separated)',
		'hide_gmail'    => 'Also replace any Gmail address shown on the site with the customer email',
		'grievance'     => 'Grievance officer: name and designation (Returns and Refunds page)',
		'panel_types'   => 'Panel boards you build (comma separated, for the Custom Panel Boards page)',
		'tray_types'    => 'Cable trays you make (comma separated)',
		'term_seo'   => 'Category and brand pages: use this plugin\'s "... in Bengaluru" titles and descriptions, also where Rank Math has one saved',
	);
	echo '<div class="wrap"><h1>RTech AI &amp; Search Helper</h1>';
	echo '<p>Check the AI guide here: <a href="' . esc_url( home_url( '/llms.txt' ) ) . '" target="_blank">' . esc_html( home_url( '/llms.txt' ) ) . '</a>. After saving, purge LiteSpeed Cache.</p>';
	echo '<form method="post" action="options.php">';
	settings_fields( 'rtech_ai' );
	echo '<table class="form-table">';
	foreach ( $fields as $k => $label ) {
		echo '<tr><th><label for="rtech_ai_' . esc_attr( $k ) . '">' . esc_html( $label ) . '</label></th><td>';
		if ( in_array( $k, array( 'term_seo', 'brand_bar', 'hide_gmail' ), true ) ) {
			echo '<input type="checkbox" id="rtech_ai_' . esc_attr( $k ) . '" name="rtech_ai_settings[' . esc_attr( $k ) . ']" value="yes"' . checked( 'yes', $s[ $k ], false ) . '>';
		} elseif ( in_array( $k, array( 'about', 'home_desc', 'shop_desc', 'profiles' ), true ) ) {
			echo '<textarea class="large-text" rows="4" id="rtech_ai_' . esc_attr( $k ) . '" name="rtech_ai_settings[' . esc_attr( $k ) . ']">' . esc_textarea( $s[ $k ] ) . '</textarea>';
		} else {
			echo '<input class="regular-text" id="rtech_ai_' . esc_attr( $k ) . '" name="rtech_ai_settings[' . esc_attr( $k ) . ']" value="' . esc_attr( $s[ $k ] ) . '">';
		}
		echo '</td></tr>';
	}
	echo '</table>';
	submit_button();
	echo '</form></div>';
}

add_filter(
	'plugin_action_links_' . plugin_basename( __FILE__ ),
	function ( $links ) {
		array_unshift( $links, '<a href="' . esc_url( admin_url( 'options-general.php?page=rtech-ai' ) ) . '">Settings</a>' );
		return $links;
	}
);
