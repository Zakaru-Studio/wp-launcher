<?php
/**
 * Connexion automatique d'Adminer à la base Postgres du projet.
 *
 * Équivalent du PMA_USER/PMA_PASSWORD de phpMyAdmin : Adminer n'écoute que
 * sur l'interface d'admin (WPL_ADMIN_BIND, loopback par défaut), et les
 * identifiants viennent de l'environnement du conteneur.
 *
 * Adminer exige un POST du formulaire de connexion (avec son jeton CSRF)
 * pour ouvrir une session : le formulaire est donc rempli en champs cachés
 * et soumis tout seul. Après un échec (l'URL porte alors `username`), on
 * rend la main au formulaire standard pour ne pas boucler.
 */
class WplAutologin extends Adminer\Plugin {
	function credentials() {
		return array('postgres', getenv('WPL_DB_USER'), getenv('WPL_DB_PASSWORD'));
	}

	function login($login, $password) {
		return true;
	}

	function loginForm() {
		if (isset($_GET['username'])) {
			return null;
		}
		$fields = array(
			'driver' => 'pgsql',
			'server' => 'postgres',
			'username' => getenv('WPL_DB_USER'),
			'password' => '-',
			'db' => getenv('WPL_DB_NAME'),
		);
		foreach ($fields as $name => $value) {
			echo "<input type='hidden' name='auth[$name]' value='" . Adminer\h($value) . "'>\n";
		}
		echo "<p><input type='submit' value='Connexion…'>\n";
		echo Adminer\script("qsl('form').submit();");
		return true;
	}
}

return new WplAutologin();
