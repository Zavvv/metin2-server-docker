<?php
	// Turkish patch: the ItemShop in Turkish for a Turkish player.
	//
	// The shop is written in Polish (pages/*.php, the seeded item rows). Instead of
	// touching every page, the finished page goes through itemshop_tr_html() (an
	// ob_start callback in index.php; itemshop_tr_json() for the wheel's JSON) and
	// every text between tags, every title/alt/placeholder and every string of the
	// page's own script that is exactly one of lang_tr_table.php's Polish texts is
	// replaced by its Turkish. A Polish reader gets the page byte for byte as before.
	//
	// The language, first match wins:
	//   ?lang=tr / ?lang=pl              (remembered in the session)
	//   the session                      (ishop/index.php sets it at the in-game login
	//                                     from the client's language: the quest flag
	//                                     playerbot_lang.code, 6 = Turkish)
	//   the browser's first language     (Accept-Language "tr" or "tr-*")
	//   Polish
	//
	// The table is rendered by tr-build/tools/panels_tr_apply.py (lang_tr_table.php).

	function itemshop_lang() {
		static $lang = null;
		if ($lang !== null) {
			return $lang;
		}
		if (isset($_GET['lang']) && ($_GET['lang'] === 'tr' || $_GET['lang'] === 'pl')) {
			if (session_status() === PHP_SESSION_ACTIVE) {
				$_SESSION['ishop_lang'] = $_GET['lang'];
			}
			return $lang = $_GET['lang'];
		}
		if (session_status() === PHP_SESSION_ACTIVE && isset($_SESSION['ishop_lang'])
				&& ($_SESSION['ishop_lang'] === 'tr' || $_SESSION['ishop_lang'] === 'pl')) {
			return $lang = $_SESSION['ishop_lang'];
		}
		$accept = isset($_SERVER['HTTP_ACCEPT_LANGUAGE']) ? $_SERVER['HTTP_ACCEPT_LANGUAGE'] : '';
		$parts = explode(',', $accept);
		$first = strtolower(trim(explode(';', $parts[0])[0]));
		if ($first === 'tr' || strpos($first, 'tr-') === 0) {
			return $lang = 'tr';
		}
		return $lang = 'pl';
	}

	// The in-game player's language, for ishop/index.php: 'tr' when the client said
	// Turkish at its last login (quest flag playerbot_lang.code == 6), else 'pl'.
	function itemshop_player_lang($sqlServ, $pid) {
		$res = @mysqli_query($sqlServ, "SELECT lValue FROM player.quest WHERE dwPID = '" . (int)$pid
			. "' AND szName = 'playerbot_lang' AND szState = 'code' LIMIT 1");
		$row = $res ? mysqli_fetch_assoc($res) : null;
		return ($row && (int)$row['lValue'] === 6) ? 'tr' : 'pl';
	}

	function itemshop_tr_table() {
		static $table = null;
		if ($table === null) {
			$file = __DIR__ . '/lang_tr_table.php';
			$table = is_file($file) ? (include $file) : array();
			if (!is_array($table)) {
				$table = array();
			}
		}
		return $table;
	}

	// One text: the Turkish of an exactly matching Polish text (whitespace collapsed),
	// with the text's own leading/trailing whitespace kept; else the text unchanged.
	function itemshop_tr_text($text) {
		$table = itemshop_tr_table();
		$core = trim($text);
		if ($core === '') {
			return $text;
		}
		$key = preg_replace('/\s+/u', ' ', $core);
		if (!isset($table[$key])) {
			// a dynamic text the shop builds around a number
			$out = itemshop_tr_dynamic($key);
			if ($out === null) {
				return $text;
			}
		} else {
			$out = $table[$key];
		}
		$lead = substr($text, 0, strpos($text, $core));
		$trail = substr($text, strlen($lead) + strlen($core));
		return $lead . $out . $trail;
	}

	function itemshop_tr_dynamic($key) {
		if (preg_match('/^Za malo Smoczych Monet \(SM\)\. Masz (\d+), potrzeba (\d+)\.$/u', $key, $m)) {
			return 'Yeterli Ejderha Parası (EP) yok. Bakiyen: ' . $m[1] . ', gereken: ' . $m[2] . '.';
		}
		// quality pass: the item cards' "Ilosc: N - Cena:" and their price, whose
		// currency is written SM (Smocze Monety) / SZ (Smocze Znaki)
		if (preg_match('/^Ilosc: (\d+) - Cena:$/u', $key, $m)) {
			return 'Miktar: ' . $m[1] . ' - Fiyat:';
		}
		if (preg_match('/^((?:&nbsp;)?[\d ]+) (SM|SZ)(\.?)$/u', $key, $m)) {
			return $m[1] . ' ' . ($m[2] === 'SM' ? 'EP' : 'EM') . $m[3];
		}
		return null;
	}

	function itemshop_tr_html($html) {
		if (itemshop_lang() !== 'tr' || $html === '') {
			return $html;
		}
		$html = preg_replace('/<html lang="pl"/', '<html lang="tr"', $html, 1);
		// the page's own scripts: a string literal that is a Polish text of the table
		$html = preg_replace_callback('/(<script\b[^>]*>)(.*?)(<\/script>)/is', function ($m) {
			$js = preg_replace_callback("/'((?:[^'\\\\\\n]|\\\\.)*)'|\"((?:[^\"\\\\\\n]|\\\\.)*)\"/u", function ($s) {
				$quote = $s[0][0];
				$inner = $quote === "'" ? $s[1] : $s[2];
				$out = itemshop_tr_text($inner);
				if ($out === $inner) {
					return $s[0];
				}
				return $quote . str_replace(array('\\', $quote), array('\\\\', '\\' . $quote), $out) . $quote;
			}, $m[2]);
			return $m[1] . $js . $m[3];
		}, $html);
		// everything else: split into tags and text; scripts and styles stay as they are
		$parts = preg_split('/(<script\b.*?<\/script>|<style\b.*?<\/style>|<!--.*?-->|<[^>]+>)/is', $html, -1,
			PREG_SPLIT_DELIM_CAPTURE);
		foreach ($parts as $i => $part) {
			if ($part === '') {
				continue;
			}
			if ($part[0] === '<') {
				if (stripos($part, '<script') === 0 || stripos($part, '<style') === 0 || strpos($part, '<!--') === 0) {
					continue;
				}
				$parts[$i] = preg_replace_callback('/\b(title|alt|placeholder|value)="([^"]*)"/i', function ($a) {
					$out = itemshop_tr_text($a[2]);
					if ($out === $a[2]) {
						return $a[0];
					}
					return $a[1] . '="' . htmlspecialchars($out, ENT_QUOTES, 'UTF-8') . '"';
				}, $part);
				continue;
			}
			$parts[$i] = itemshop_tr_text($part);
		}
		return implode('', $parts);
	}

	// The wheel's JSON answers: the error message and the prize names / descriptions.
	function itemshop_tr_json($body) {
		if (itemshop_lang() !== 'tr' || $body === '') {
			return $body;
		}
		$data = json_decode($body, true);
		if (!is_array($data)) {
			return $body;
		}
		foreach (array('error', 'name', 'desc') as $field) {
			if (isset($data[$field]) && is_string($data[$field])) {
				$data[$field] = itemshop_tr_text($data[$field]);
			}
		}
		if (isset($data['items']) && is_array($data['items'])) {
			foreach ($data['items'] as $k => $item) {
				if (is_array($item) && isset($item['name']) && is_string($item['name'])) {
					$data['items'][$k]['name'] = itemshop_tr_text($item['name']);
				}
			}
		}
		return json_encode($data);
	}
