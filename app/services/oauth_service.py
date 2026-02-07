"""
OAuth Service for GitHub authentication
"""
import requests
from flask import url_for


class GitHubOAuthService:
    """Service for GitHub OAuth authentication"""
    
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.authorize_url = 'https://github.com/login/oauth/authorize'
        self.token_url = 'https://github.com/login/oauth/access_token'
        self.api_url = 'https://api.github.com'
    
    def get_authorization_url(self, redirect_uri, state):
        """Get GitHub OAuth authorization URL"""
        return f"{self.authorize_url}?client_id={self.client_id}&redirect_uri={redirect_uri}&scope=read:user,user:email&state={state}"
    
    def exchange_code_for_token(self, code, redirect_uri):
        """Exchange authorization code for access token"""
        try:
            response = requests.post(self.token_url, json={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'code': code,
                'redirect_uri': redirect_uri
            }, headers={'Accept': 'application/json'}, timeout=10)
            
            return response.json()
        except Exception as e:
            return {'error': str(e)}
    
    def get_user_info(self, access_token):
        """Get user information from GitHub API"""
        try:
            headers = {'Authorization': f'token {access_token}'}
            
            # Get user data
            user_response = requests.get(f"{self.api_url}/user", headers=headers, timeout=10)
            user = user_response.json()
            
            # Get user emails
            emails_response = requests.get(f"{self.api_url}/user/emails", headers=headers, timeout=10)
            emails = emails_response.json()
            
            # Get SSH keys
            keys_response = requests.get(f"{self.api_url}/user/keys", headers=headers, timeout=10)
            keys = keys_response.json()
            
            # Find primary email
            primary_email = user.get('email')
            if isinstance(emails, list):
                for email_obj in emails:
                    if email_obj.get('primary'):
                        primary_email = email_obj.get('email')
                        break
            
            # Extract SSH keys
            ssh_keys = []
            if isinstance(keys, list):
                ssh_keys = [k.get('key') for k in keys if k.get('key')]
            
            return {
                'github_id': user.get('id'),
                'username': user.get('login'),
                'email': primary_email or user.get('email'),
                'name': user.get('name', ''),
                'avatar_url': user.get('avatar_url'),
                'ssh_keys': ssh_keys
            }
        except Exception as e:
            return {'error': str(e)}






