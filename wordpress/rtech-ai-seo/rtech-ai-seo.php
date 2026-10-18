<?php
/**
 * Plugin Name:       RTech AI & Search Helper
 * Description:       Makes the shop easy for Google and AI assistants (ChatGPT, Gemini, Perplexity, Claude) to read: clean product descriptions, Product data on every product (Request a Quote ones too), one business name, readable breadcrumbs, a share image, and /llms.txt. Changes no prices, stock or product content.
 * Version:           1.0.0
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

define( 'RTECH_AI_VERSION', '1.0.0' );

/** Site-wide facts. Edit under Settings > RTech AI. */
function rtech_ai_settings() {
	$defaults = array(
		'brand_name' => 'RTechElectricals',
		'trade_name' => 'RAMTECH AUTOMATION',
		'city'       => 'Bengaluru',
		'email'      => '',
		'phone'      => '',
		'about'      => 'RTechElectricals is an authorised dealer of electrical products in Bengaluru, Karnataka, India: wires and cables, modular switches, MCBs and switchgear, lighting, fans and pumps from Havells, Legrand, Polycab, KEI, RR Kabel, Finolex, GM and other brands. Prices shown on the site include GST. Products without a listed price can be quoted on request.',
		'home_desc'  => 'Authorised dealer in Bengaluru for Havells, Legrand, Polycab, KEI, RR Kabel and Finolex. 5,000+ wires, cables, switches, MCBs and lights. GST prices, order online.',
	);
	$saved = get_option( 'rtech_ai_settings', array() );
	return wp_parse_args( is_array( $saved ) ? array_filter( $saved, 'strlen' ) : array(), $defaults );
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
	return $description;
}
add_filter( 'rank_math/frontend/description', 'rtech_ai_filter_description', 20 );
add_filter( 'rank_math/opengraph/facebook/og_description', 'rtech_ai_filter_description', 20 );
add_filter( 'rank_math/opengraph/twitter/twitter_description', 'rtech_ai_filter_description', 20 );

/** "Name - rtechelectricals" -> "Name | RTechElectricals" (the name the rest of the site uses). */
function rtech_ai_filter_title( $title ) {
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
		if ( isset( $data['publisher'] ) && is_array( $data['publisher'] ) ) {
			$old = isset( $data['publisher']['name'] ) ? $data['publisher']['name'] : '';
			$data['publisher']['name'] = $s['brand_name'];
			if ( $old && strcasecmp( $old, $s['brand_name'] ) !== 0 ) {
				$data['publisher']['alternateName'] = $old;
			} elseif ( $s['trade_name'] ) {
				$data['publisher']['alternateName'] = $s['trade_name'];
			}
			$data['publisher']['url'] = home_url( '/' );
			$data['publisher']['description'] = $s['about'];
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
	$lines = array( '# ' . $s['brand_name'], '', '> ' . $s['about'], '' );

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
	if ( $addr ) {
		$facts[] = '- Address: ' . implode( ', ', $addr );
	}
	if ( $s['phone'] ) {
		$facts[] = '- Phone / WhatsApp: ' . $s['phone'];
	}
	if ( $s['email'] ) {
		$facts[] = '- Email: ' . $s['email'];
	}
	$facts[] = '- Prices include GST; products with a price can be ordered online (add to cart).';
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
	foreach ( array( 'about', 'about-us', 'contact', 'contact-us', 'shipping', 'shipping-policy', 'delivery', 'refund', 'refund-policy', 'returns', 'return-policy', 'refund_returns', 'terms', 'terms-and-conditions', 'faq', 'faqs', 'upload-boq', 'bulk-order', 'request-a-quote' ) as $slug ) {
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
					foreach ( array( 'brand_name', 'trade_name', 'city', 'email', 'phone', 'home_desc', 'about' ) as $k ) {
						$out[ $k ] = isset( $in[ $k ] ) ? sanitize_textarea_field( $in[ $k ] ) : '';
					}
					$out['email'] = sanitize_email( $out['email'] );
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
		'city'       => 'City',
		'email'      => 'Customer email (shown in /llms.txt)',
		'phone'      => 'Customer phone / WhatsApp (shown in /llms.txt)',
		'home_desc'  => 'Home page description (Google shows about 155 characters)',
		'about'      => 'About the business (top of /llms.txt and the business data)',
	);
	echo '<div class="wrap"><h1>RTech AI &amp; Search Helper</h1>';
	echo '<p>Check the AI guide here: <a href="' . esc_url( home_url( '/llms.txt' ) ) . '" target="_blank">' . esc_html( home_url( '/llms.txt' ) ) . '</a>. After saving, purge LiteSpeed Cache.</p>';
	echo '<form method="post" action="options.php">';
	settings_fields( 'rtech_ai' );
	echo '<table class="form-table">';
	foreach ( $fields as $k => $label ) {
		echo '<tr><th><label for="rtech_ai_' . esc_attr( $k ) . '">' . esc_html( $label ) . '</label></th><td>';
		if ( in_array( $k, array( 'about', 'home_desc' ), true ) ) {
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
