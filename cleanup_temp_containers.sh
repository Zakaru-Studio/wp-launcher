#!/bin/bash

echo "🧹 Nettoyage des conteneurs temporaires..."

# Arrêter et supprimer les conteneurs PHPMyAdmin temporaires
echo "Arrêt des PHPMyAdmin temporaires..."
docker stop temp_phpmyadmin_akdigital temp_phpmyadmin_express temp_phpmyadmin_lesbijouxchics temp_phpmyadmin_nonasolution temp_phpmyadmin_testproject 2>/dev/null || true
docker rm temp_phpmyadmin_akdigital temp_phpmyadmin_express temp_phpmyadmin_lesbijouxchics temp_phpmyadmin_nonasolution temp_phpmyadmin_testproject 2>/dev/null || true

# Arrêter et supprimer les conteneurs MySQL temporaires
echo "Arrêt des MySQL temporaires..."
docker stop temp_mysql_akdigital temp_mysql_express temp_mysql_lesbijouxchics temp_mysql_nonasolution temp_mysql_testproject 2>/dev/null || true
docker rm temp_mysql_akdigital temp_mysql_express temp_mysql_lesbijouxchics temp_mysql_nonasolution temp_mysql_testproject 2>/dev/null || true

echo "✅ Nettoyage terminé !"
echo "Ports libérés : 8121, 8122, 8123, 8124, 8125" 