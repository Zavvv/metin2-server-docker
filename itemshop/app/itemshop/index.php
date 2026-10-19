<?php
	// error_reporting(0);
	// Output buffering: pages/*.php redirect with header("Location: ...") after
	// the <head>/<body> above has already printed, which would otherwise fail
	// with "headers already sent" and silently strand the visitor on a blank
	// page instead of bouncing them to the login form.
	// Turkish patch: the finished page goes through itemshop_tr_html (lang_tr.php),
	// which returns it unchanged for a Polish reader.
	require(__DIR__ . "/lang_tr.php");
	ob_start('itemshop_tr_html');
	session_start();
	require("../user/config.php");
	itemshop_lang();

	// Podglad katalogu bez logowania (osadzany w iframe na m2singleplayer.pl).
	// Celowo NIE oparty o sesje/cookie - w iframe z innej domeny przegladarki
	// czesto blokuja cookie trzeciej strony, wiec kazde zadanie dostawaloby
	// pusta sesje i trafialoby na "dostep zabroniony" mimo ?preview=1 w URL.
	// Zamiast tego ?preview=1 jest doklejane do KAZDEGO linku wewnatrz sklepu
	// (patrz pages/etc.php, home.php, category.php, detail.php) i kazda strona
	// sama sprawdza $_GET['preview'] - bezstanowo, bez potrzeby ciastka.
?>
<!DOCTYPE html>
<html lang="pl" >
	<head>
		<?php include("./head.php"); ?>
	</head>
	<body class="twoColFixLtHdr" scroll="no">
		<?php
			$page = (isset($_GET['s']) && !empty($_GET['s'])) ? basename($_GET['s']) : "home";
			if(file_exists("./pages/".$page.".php")) {
				include("./pages/".$page.".php");
			} else {
				include("./pages/home.php");
			}?>
	</body>
</html>
<?php mysqli_close($sqlServ); ?>
