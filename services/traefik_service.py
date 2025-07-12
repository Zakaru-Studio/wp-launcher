#!/usr/bin/env python3
"""
Service de gestion Traefik - DÉSACTIVÉ
L'exposition publique des sites a été supprimée pour privilégier l'accès local uniquement.
"""

class TraefikService:
    """Service Traefik désactivé - Accès local uniquement"""
    
    def __init__(self, *args, **kwargs):
        pass
    
    def expose_site(self, *args, **kwargs):
        return {'success': False, 'message': 'Exposition publique désactivée - Utilisez l\'accès local uniquement'}
    
    def unexpose_site(self, *args, **kwargs):
        return {'success': False, 'message': 'Exposition publique désactivée'}
    
    def get_exposed_sites(self):
        return {}
    
    def get_traefik_status(self):
        return {'success': False, 'message': 'Traefik désactivé'}
    
    def start_traefik(self):
        return {'success': False, 'message': 'Traefik désactivé'} 