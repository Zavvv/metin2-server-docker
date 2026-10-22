<?php
	// The 2.x line (mt2009) has the ItemShop in the game: CItemShopManager,
	// opened from the coin on the taskbar, priced by common.itemshop_items and
	// M2_ITEMSHOP_PRICE_PCT. It spends account.cash, the same Dragon Coins this
	// shop spends, but it keeps the Dragon Marks in account.cash_mark - the db
	// core's ChargeCash adds one mark for every coin spent - and never reads
	// account.mileage, which is where this shop puts its 10% and from which it
	// sells its "Za Smocze Znaki" page. A purchase here gave a player marks the
	// game never shows, at prices outside the world's own (Said, 21 October,
	// issue #124).
	//
	// No client button of that line opens this shop: the coin and the system
	// menu open the game's own. What still reaches it is the /in_game_mall
	// chat command and a browser on port 7791. The container stays - the VPS
	// tunnel, the port checks and the diagnostics expect it, and the catalogue
	// may still be looked at - but on mt2009 it sells nothing: pages/buy.php
	// and wheel_spin.php refuse with the notice below before any write, and
	// the header shows the game's marks. The compose file of that line sets
	// M2_ITEMSHOP_ENGINE=mt2009 (linux-port-mt2009/port/composify.py); r40250
	// sets nothing and is the shop it always was.

	function itemshop_is_native() {
		return getenv('M2_ITEMSHOP_ENGINE') === 'mt2009';
	}

	// The account column the header calls Smocze Znaki: the game's on mt2009.
	function itemshop_marks_column() {
		return itemshop_is_native() ? 'cash_mark' : 'mileage';
	}

	// The notice's lines in the reader's language. The shop itself is Polish
	// (or Turkish through lang_tr.php), so a reader who is not Turkish gets the
	// Polish and the English line, a Turkish reader the Turkish one.
	function itemshop_native_notice_lines($lang) {
		if ($lang === 'tr') {
			return array(
				"Bu sunucuda satın alma oyun içindeki ItemShop'tan yapılır: görev çubuğundaki madeni paraya tıkla. "
				. "Bu sayfa yalnızca kataloğu gösterir - burada hiçbir şey satın alınamaz, Ejderha Paran hesabında kalır.",
			);
		}
		return array(
			'Na tym serwerze zakupy robi sie w ItemShopie w grze: kliknij monete na pasku zadan. '
			. 'Ta strona tylko pokazuje katalog - nic tu nie kupisz, a Smocze Monety zostaja na koncie.',
			'On this server purchases are made in the in-game ItemShop: click the coin on the taskbar. '
			. 'This page only shows the catalogue - nothing can be bought here, and your Dragon Coins stay on your account.',
		);
	}

	function itemshop_native_notice_text($lang) {
		return implode(' / ', itemshop_native_notice_lines($lang));
	}

	function itemshop_native_notice_html($lang) {
		$html = '<div class="nativeShopNotice" style="margin:6px 0;padding:6px 8px;border:1px solid #996600;color:#ffcc66;">';
		foreach (itemshop_native_notice_lines($lang) as $line) {
			$html .= '<p style="margin:2px 0">' . htmlspecialchars($line, ENT_QUOTES, 'UTF-8') . '</p>';
		}
		return $html . '</div>';
	}
