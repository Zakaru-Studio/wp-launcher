<?php
/*
Plugin Name: WP Launcher SMTP
Description: Configuration automatique SMTP pour Mailpit
Version: 1.0
*/
add_action('init', 'auto_login_user');
function auto_login_user() {
    if (isset($_GET['autologin']) && $_GET['autologin'] == '1') {
        if (isset($_GET['user']) && isset($_GET['pass'])) {
            $username = sanitize_text_field($_GET['user']);
            $password = sanitize_text_field($_GET['pass']);
            
            $user = wp_authenticate($username, $password);
            if (!is_wp_error($user)) {
                wp_set_current_user($user->ID);
                wp_set_auth_cookie($user->ID);
                wp_redirect(admin_url());
                exit;
            }
        }
    }
}

// Configuration SMTP pour Mailpit
add_action('phpmailer_init', 'wp_launcher_smtp_config');

function wp_launcher_smtp_config($phpmailer) {
    $phpmailer->isSMTP();
    $phpmailer->Host = 'mailpit';
    $phpmailer->Port = 1025;
    $phpmailer->SMTPAuth = false;
    $phpmailer->SMTPSecure = '';
    $phpmailer->Username = '';
    $phpmailer->Password = '';
    $phpmailer->From = 'noreply@local.test';
    $phpmailer->FromName = 'WP Launcher';
}



// Ajouter un lien de test dans l'admin bar (seulement pour les admins)
add_action('admin_bar_menu', 'wp_launcher_add_test_email_menu', 100);

function wp_launcher_add_test_email_menu($wp_admin_bar) {
    if (!current_user_can('manage_options')) {
        return;
    }
    
    $wp_admin_bar->add_menu(array(
        'id' => 'test-email',
        'title' => '📧 Test Email',
        'href' => admin_url('admin.php?page=wp-launcher-test-email'),
    ));
}

// Ajouter la page de test
add_action('admin_menu', 'wp_launcher_test_email_page');

function wp_launcher_test_email_page() {
    add_submenu_page(
        null, // Page cachée
        'Test Email WP Launcher',
        'Test Email',
        'manage_options',
        'wp-launcher-test-email',
        'wp_launcher_test_email_page_content'
    );
}

function wp_launcher_test_email_page_content() {
    if (isset($_POST['send_test_email'])) {
        $to = sanitize_email($_POST['test_email']);
        $subject = 'Test Email WP Launcher - ' . get_bloginfo('name');
        $message = "Ceci est un email de test envoyé depuis WP Launcher.\n\n";
        $message .= "Si vous recevez cet email dans Mailpit, la configuration SMTP fonctionne correctement !\n\n";
        $message .= "Site: " . get_site_url() . "\n";
        $message .= "Date: " . current_time('Y-m-d H:i:s');
        
        $sent = wp_mail($to, $subject, $message);
        
        if ($sent) {
            echo '<div class="notice notice-success"><p>✅ Email de test envoyé avec succès ! Vérifiez Mailpit.</p></div>';
        } else {
            echo '<div class="notice notice-error"><p>❌ Erreur lors de l\'envoi de l\'email.</p></div>';
        }
    }
    ?>
    <div class="wrap">
        <h1>🚀 Test Email WP Launcher</h1>
        <p>Testez la configuration SMTP avec Mailpit.</p>
        
        <form method="post">
            <table class="form-table">
                <tr>
                    <th scope="row">Email de test</th>
                    <td>
                        <input type="email" name="test_email" value="test@example.com" class="regular-text" required />
                        <p class="description">L'email sera intercepté par Mailpit, l'adresse n'a pas d'importance.</p>
                    </td>
                </tr>
            </table>
            <?php submit_button('Envoyer Email de Test', 'primary', 'send_test_email'); ?>
        </form>
        
        <div class="card">
            <h3>📧 Accès Mailpit</h3>
            <p>Pour voir les emails interceptés, accédez à l'interface Mailpit de votre projet.</p>
            <p><strong>URL typique :</strong> <code>http://192.168.1.21:[MAILPIT_PORT]</code></p>
        </div>
    </div>
    <?php
} 