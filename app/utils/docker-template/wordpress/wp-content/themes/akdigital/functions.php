<?php

if (!defined('ABSPATH')) {
    exit;
}

// remove access page lost password
add_action('login_init', 'otfmh_disable_lost_password');
function otfmh_disable_lost_password()
{
    if (isset($_GET['action'])) {
        if (in_array($_GET['action'], array('lostpassword', 'retrievepassword'))) {
            wp_redirect(wp_login_url(), 301);
            exit;
        }
    }
}

// add css on login page
add_action('login_enqueue_scripts', 'otfmh_login_page_resource');
function otfmh_login_page_resource()
{
    wp_deregister_script('password-strength-meter');

    wp_dequeue_style('login');

    wp_enqueue_style('otfm_login_page_css', get_stylesheet_directory_uri() . '/assets/css/login-page.css');
}

// remove title seo
add_filter('login_title', 'otfmh_remove_title_wp');
function otfmh_remove_title_wp()
{
    return __('Log In &lsaquo;', 'otfm-headless') . ' ' . get_bloginfo('name', 'display');
}

// disable Powered by WordPress - on login form
add_filter('login_headertext', '__return_false');

// disable link (Powered by WordPress) - on login form
add_filter('login_headerurl', '__return_false');

// close register
add_filter('allow_password_reset', '__return_false');

// disable link on password_reset
add_filter('lostpassword_url', '__return_false');

add_filter('gettext', 'otfmh_remove_lostpassword_text');
function otfmh_remove_lostpassword_text($text)
{
    if (!in_array($GLOBALS['pagenow'], array('wp-login.php')))
        return $text;

    if ($text == 'Lost your password?') {
        return '';
    }
    return $text;
}

add_filter('gettext_with_context', 'otfmh_custom_login_text');
function otfmh_custom_login_text($text)
{
    if (!in_array($GLOBALS['pagenow'], array('wp-login.php')))
        return $text;

    if ($text == '&larr; Back to %s') {
        return '';
    }
    return $text;
}

// disable RSS Feed
add_action('do_feed', 'otfmh_disable_feed', 1);
add_action('do_feed_rdf', 'otfmh_disable_feed', 1);
add_action('do_feed_rss', 'otfmh_disable_feed', 1);
add_action('do_feed_rss2', 'otfmh_disable_feed', 1);
add_action('do_feed_atom', 'otfmh_disable_feed', 1);
add_action('do_feed_rss2_comments', 'otfmh_disable_feed', 1);
add_action('do_feed_atom_comments', 'otfmh_disable_feed', 1);
function otfmh_disable_feed()
{
    wp_die(__('Access denied', 'otfm-headless'));
}

// Changer Articles en Publications
add_action('init', 'otfmh_change_post_labels');
function otfmh_change_post_labels()
{
    global $wp_post_types;

    $labels                     = &$wp_post_types['post']->labels;
    $labels->name               = 'Publications';
    $labels->singular_name      = 'Publication';
    $labels->add_new            = 'Ajouter une nouvelle';
    $labels->add_new_item       = 'Ajouter une nouvelle publication';
    $labels->edit_item          = 'Modifier la publication';
    $labels->new_item           = 'Nouvelle publication';
    $labels->view_item          = 'Voir la publication';
    $labels->search_items       = 'Rechercher des publications';
    $labels->not_found          = 'Aucune publication trouvée';
    $labels->not_found_in_trash = 'Aucune publication trouvée dans la corbeille';
    $labels->all_items          = 'Toutes les publications';
    $labels->menu_name          = 'Publications';
    $labels->name_admin_bar     = 'Publication';
}

// Changer le menu dans l'admin
add_action('admin_menu', 'otfmh_change_post_menu_label');
function otfmh_change_post_menu_label()
{
    global $menu;
    global $submenu;
    $menu[5][0]                 = 'Publications';
    $submenu['edit.php'][5][0]  = 'Toutes les publications';
    $submenu['edit.php'][10][0] = 'Ajouter une publication';
}

// Activer le support des images mises en avant
add_action('after_setup_theme', 'otfmh_enable_featured_images');
function otfmh_enable_featured_images()
{
    add_theme_support('post-thumbnails');

    // Optionnel : définir des tailles d'images personnalisées
    add_image_size('publication-thumb', 300, 200, true); // 300px de large, 200px de haut, recadrée
    add_image_size('publication-large', 800, 600, true); // 800px de large, 600px de haut, recadrée
}

// Enregistrement de la taxonomie "Type de veille"
add_action('init', 'otfmh_register_taxonomy_type_de_veille');
function otfmh_register_taxonomy_type_de_veille()
{
    register_taxonomy('type-de-veille', array('veille-geopolitique'), array(
        'labels'              => array(
            'name'                       => 'Type de veilles',
            'singular_name'              => 'Type de veille',
            'menu_name'                  => 'Type de veilles',
            'all_items'                  => 'Tous les Type de veilles',
            'edit_item'                  => 'Modifier Type de veille',
            'view_item'                  => 'Voir Type de veille',
            'update_item'                => 'Mettre à jour Type de veille',
            'add_new_item'               => 'Ajouter Type de veille',
            'new_item_name'              => 'Nom du nouveau Type de veille',
            'search_items'               => 'Rechercher Type de veilles',
            'popular_items'              => 'Type de veilles populaire',
            'separate_items_with_commas' => 'Séparer les type de veilles avec une virgule',
            'add_or_remove_items'        => 'Ajouter ou retirer type de veilles',
            'choose_from_most_used'      => 'Choisir parmi les type de veilles les plus utilisés',
            'not_found'                  => 'Aucun type de veilles trouvé',
            'no_terms'                   => 'Aucun type de veilles',
            'items_list_navigation'      => 'Navigation dans la liste Type de veilles',
            'items_list'                 => 'Liste Type de veilles',
            'back_to_items'              => '← Aller à « type de veilles »',
            'item_link'                  => 'Lien Type de veille',
            'item_link_description'      => 'Un lien vers un type de veille',
        ),
        'public'              => true,
        'show_in_menu'        => true,
        'show_in_rest'        => true,
        'show_in_graphql'     => true,
        'graphql_single_name' => 'typeDeVeille',
        'graphql_plural_name' => 'typeDeVeilles',
    ));
}

// Enregistrement des Custom Post Types
add_action('init', 'otfmh_register_custom_post_types');
function otfmh_register_custom_post_types()
{

    // CPT Formation
    register_post_type('formation', array(
        'labels'              => array(
            'name'                     => 'Formations',
            'singular_name'            => 'Formation',
            'menu_name'                => 'Formations',
            'all_items'                => 'Tous les Formations',
            'edit_item'                => 'Modifier Formation',
            'view_item'                => 'Voir Formation',
            'view_items'               => 'Voir Formations',
            'add_new_item'             => 'Ajouter Formation',
            'add_new'                  => 'Ajouter Formation',
            'new_item'                 => 'Nouveau Formation',
            'parent_item_colon'        => 'Formation parent :',
            'search_items'             => 'Rechercher Formations',
            'not_found'                => 'Aucun formations trouvé',
            'not_found_in_trash'       => 'Aucun formations trouvé dans la corbeille',
            'archives'                 => 'Archives des Formation',
            'attributes'               => 'Attributs des Formation',
            'insert_into_item'         => 'Insérer dans formation',
            'uploaded_to_this_item'    => 'Téléversé sur ce formation',
            'filter_items_list'        => 'Filtrer la liste formations',
            'filter_by_date'           => 'Filtrer formations par date',
            'items_list_navigation'    => 'Navigation dans la liste Formations',
            'items_list'               => 'Liste Formations',
            'item_published'           => 'Formation publié.',
            'item_published_privately' => 'Formation publié en privé.',
            'item_reverted_to_draft'   => 'Formation repassé en brouillon.',
            'item_scheduled'           => 'Formation planifié.',
            'item_updated'             => 'Formation mis à jour.',
            'item_link'                => 'Lien Formation',
            'item_link_description'    => 'Un lien vers un formation.',
        ),
        'public'              => true,
        'show_in_rest'        => true,
        'menu_icon'           => 'dashicons-admin-post',
        'supports'            => array('title', 'editor', 'thumbnail', 'custom-fields'),
        'delete_with_user'    => false,
        'show_in_graphql'     => true,
        'graphql_single_name' => 'formation',
        'graphql_plural_name' => 'formations',
    ));

    // CPT Podcast
    register_post_type('podcast', array(
        'labels'              => array(
            'name'                     => 'Podcasts',
            'singular_name'            => 'Podcast',
            'menu_name'                => 'Podcasts',
            'all_items'                => 'Tous les Podcasts',
            'edit_item'                => 'Modifier Podcast',
            'view_item'                => 'Voir Podcast',
            'view_items'               => 'Voir Podcasts',
            'add_new_item'             => 'Ajouter Podcast',
            'add_new'                  => 'Ajouter Podcast',
            'new_item'                 => 'Nouveau Podcast',
            'parent_item_colon'        => 'Podcast parent :',
            'search_items'             => 'Rechercher Podcasts',
            'not_found'                => 'Aucun podcasts trouvé',
            'not_found_in_trash'       => 'Aucun podcasts trouvé dans la corbeille',
            'archives'                 => 'Archives des Podcast',
            'attributes'               => 'Attributs des Podcast',
            'insert_into_item'         => 'Insérer dans podcast',
            'uploaded_to_this_item'    => 'Téléversé sur ce podcast',
            'filter_items_list'        => 'Filtrer la liste podcasts',
            'filter_by_date'           => 'Filtrer podcasts par date',
            'items_list_navigation'    => 'Navigation dans la liste Podcasts',
            'items_list'               => 'Liste Podcasts',
            'item_published'           => 'Podcast publié.',
            'item_published_privately' => 'Podcast publié en privé.',
            'item_reverted_to_draft'   => 'Podcast repassé en brouillon.',
            'item_scheduled'           => 'Podcast planifié.',
            'item_updated'             => 'Podcast mis à jour.',
            'item_link'                => 'Lien Podcast',
            'item_link_description'    => 'Un lien vers un podcast.',
        ),
        'public'              => true,
        'show_in_rest'        => true,
        'menu_icon'           => 'dashicons-admin-post',
        'supports'            => array('title', 'editor', 'thumbnail', 'custom-fields'),
        'delete_with_user'    => false,
        'show_in_graphql'     => true,
        'graphql_single_name' => 'podcast',
        'graphql_plural_name' => 'podcasts',
    ));

    // CPT Veille géopolitique
    register_post_type('veille-geopolitique', array(
        'labels'              => array(
            'name'                     => 'Veilles géopolitique',
            'singular_name'            => 'Veille géopolitique',
            'menu_name'                => 'Veilles géopolitique',
            'all_items'                => 'Tous les Veilles géopolitique',
            'edit_item'                => 'Modifier Veille géopolitique',
            'view_item'                => 'Voir Veille géopolitique',
            'view_items'               => 'Voir Veilles géopolitique',
            'add_new_item'             => 'Ajouter Veille géopolitique',
            'add_new'                  => 'Ajouter Veille géopolitique',
            'new_item'                 => 'Nouveau Veille géopolitique',
            'parent_item_colon'        => 'Veille géopolitique parent :',
            'search_items'             => 'Rechercher Veilles géopolitique',
            'not_found'                => 'Aucun veilles géopolitique trouvé',
            'not_found_in_trash'       => 'Aucun veilles géopolitique trouvé dans la corbeille',
            'archives'                 => 'Archives des Veille géopolitique',
            'attributes'               => 'Attributs des Veille géopolitique',
            'insert_into_item'         => 'Insérer dans veille géopolitique',
            'uploaded_to_this_item'    => 'Téléversé sur ce veille géopolitique',
            'filter_items_list'        => 'Filtrer la liste veilles géopolitique',
            'filter_by_date'           => 'Filtrer veilles géopolitique par date',
            'items_list_navigation'    => 'Navigation dans la liste Veilles géopolitique',
            'items_list'               => 'Liste Veilles géopolitique',
            'item_published'           => 'Veille géopolitique publié.',
            'item_published_privately' => 'Veille géopolitique publié en privé.',
            'item_reverted_to_draft'   => 'Veille géopolitique repassé en brouillon.',
            'item_scheduled'           => 'Veille géopolitique planifié.',
            'item_updated'             => 'Veille géopolitique mis à jour.',
            'item_link'                => 'Lien Veille géopolitique',
            'item_link_description'    => 'Un lien vers un veille géopolitique.',
        ),
        'public'              => true,
        'show_in_rest'        => true,
        'menu_icon'           => 'dashicons-admin-post',
        'supports'            => array('title', 'author', 'editor', 'excerpt', 'thumbnail', 'custom-fields'),
        'taxonomies'          => array('type-de-veille'),
        'delete_with_user'    => false,
        'show_in_graphql'     => true,
        'graphql_single_name' => 'veilleGeopolitique',
        'graphql_plural_name' => 'veillesGeopolitique',
    ));

    // CPT Webinaire
    register_post_type('webinaire', array(
        'labels'              => array(
            'name'                     => 'Webinaires',
            'singular_name'            => 'Webinaire',
            'menu_name'                => 'Webinaires',
            'all_items'                => 'Tous les Webinaires',
            'edit_item'                => 'Modifier Webinaire',
            'view_item'                => 'Voir Webinaire',
            'view_items'               => 'Voir Webinaires',
            'add_new_item'             => 'Ajouter Webinaire',
            'add_new'                  => 'Ajouter Webinaire',
            'new_item'                 => 'Nouveau Webinaire',
            'parent_item_colon'        => 'Webinaire parent :',
            'search_items'             => 'Rechercher Webinaires',
            'not_found'                => 'Aucun webinaires trouvé',
            'not_found_in_trash'       => 'Aucun webinaires trouvé dans la corbeille',
            'archives'                 => 'Archives des Webinaire',
            'attributes'               => 'Attributs des Webinaire',
            'insert_into_item'         => 'Insérer dans webinaire',
            'uploaded_to_this_item'    => 'Téléversé sur ce webinaire',
            'filter_items_list'        => 'Filtrer la liste webinaires',
            'filter_by_date'           => 'Filtrer webinaires par date',
            'items_list_navigation'    => 'Navigation dans la liste Webinaires',
            'items_list'               => 'Liste Webinaires',
            'item_published'           => 'Webinaire publié.',
            'item_published_privately' => 'Webinaire publié en privé.',
            'item_reverted_to_draft'   => 'Webinaire repassé en brouillon.',
            'item_scheduled'           => 'Webinaire planifié.',
            'item_updated'             => 'Webinaire mis à jour.',
            'item_link'                => 'Lien Webinaire',
            'item_link_description'    => 'Un lien vers un webinaire.',
        ),
        'public'              => true,
        'show_in_rest'        => true,
        'menu_icon'           => 'dashicons-admin-post',
        'supports'            => array('title', 'editor', 'thumbnail', 'custom-fields'),
        'delete_with_user'    => false,
        'show_in_graphql'     => true,
        'graphql_single_name' => 'webinaire',
        'graphql_plural_name' => 'webinaires',
    ));
}

// Fonction pour calculer et enregistrer le nombre de mots
add_action('save_post', 'otfmh_calculate_word_count');
function otfmh_calculate_word_count($post_id)
{
    // Éviter l'auto-sauvegarde et les révisions
    if (wp_is_post_autosave($post_id) || wp_is_post_revision($post_id)) {
        return;
    }

    // Récupérer le contenu du post
    $post    = get_post($post_id);
    $content = $post->post_content;

    // Supprimer les shortcodes et les balises HTML
    $content = strip_shortcodes($content);
    $content = wp_strip_all_tags($content);

    // Calculer le nombre de mots
    $word_count = str_word_count($content);

    // Enregistrer en post meta
    update_post_meta($post_id, '_word_count', $word_count);
}

// Fonction pour calculer et enregistrer le temps de lecture
add_action('save_post', 'otfmh_calculate_reading_time');
function otfmh_calculate_reading_time($post_id)
{
    // Éviter l'auto-sauvegarde et les révisions
    if (wp_is_post_autosave($post_id) || wp_is_post_revision($post_id)) {
        return;
    }

    // Récupérer le nombre de mots (calculé par la fonction précédente)
    $word_count = get_post_meta($post_id, '_word_count', true);

    // Si le nombre de mots n'existe pas encore, le calculer
    if (!$word_count) {
        $post       = get_post($post_id);
        $content    = $post->post_content;
        $content    = strip_shortcodes($content);
        $content    = wp_strip_all_tags($content);
        $word_count = str_word_count($content);
    }

    // Calculer le temps de lecture (basé sur 200 mots par minute)
    $words_per_minute = 200;
    $reading_time     = ceil($word_count / $words_per_minute);

    // S'assurer qu'il y a au minimum 1 minute
    if ($reading_time < 1) {
        $reading_time = 1;
    }

    // Enregistrer en post meta
    update_post_meta($post_id, '_reading_time', $reading_time);
}

// Fonction pour générer les méta pour tous les posts existants
function otfmh_generate_meta_for_existing_posts()
{
    // Types de posts à traiter
    $post_types = array('post', 'veille-geopolitique');

    foreach ($post_types as $post_type) {
        // Récupérer tous les posts du type en question
        $posts = get_posts(array(
            'post_type'   => $post_type,
            'post_status' => 'publish',
            'numberposts' => -1, // Récupérer tous les posts
            'fields'      => 'ids' // Ne récupérer que les IDs pour optimiser
        ));

        foreach ($posts as $post_id) {
            // Récupérer le contenu du post
            $post    = get_post($post_id);
            $content = $post->post_content;

            // Supprimer les shortcodes et les balises HTML
            $content = strip_shortcodes($content);
            $content = wp_strip_all_tags($content);

            // Calculer le nombre de mots
            $word_count = str_word_count($content);

            // Calculer le temps de lecture (basé sur 200 mots par minute)
            $words_per_minute = 200;
            $reading_time     = ceil($word_count / $words_per_minute);

            // S'assurer qu'il y a au minimum 1 minute
            if ($reading_time < 1) {
                $reading_time = 1;
            }

            // Enregistrer les méta
            update_post_meta($post_id, '_word_count', $word_count);
            update_post_meta($post_id, '_reading_time', $reading_time);
        }
    }

    return true;
}

// Fonction d'aide pour exécuter via l'admin WordPress
add_action('wp_ajax_generate_meta_existing_posts', 'otfmh_ajax_generate_meta_existing_posts');
function otfmh_ajax_generate_meta_existing_posts()
{
    // Vérifier les permissions
    if (!current_user_can('manage_options')) {
        wp_die('Permissions insuffisantes');
    }

    // Exécuter la fonction
    otfmh_generate_meta_for_existing_posts();

    wp_die('Méta générés avec succès pour tous les posts existants.');
}