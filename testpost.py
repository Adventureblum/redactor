import requests

# Étape 1 : obtenir le token JWT
auth_url = "https://francerenovation-idf.com/wp-json/jwt-auth/v1/token"
auth_data = {
    "username": "mauvaisegraine",
    "password": "nVY1WxYKS(7iv(#s(!Kp#!d$"
}

auth_response = requests.post(auth_url, json=auth_data)
token = auth_response.json().get("token")

# Vérifie que tu as bien reçu un token
if not token:
    print("Erreur d'authentification :", auth_response.json())
    exit()

# Étape 2 : poster un article
post_url = "https://francerenovation-idf.com/wp-json/wp/v2/posts"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}
post_data = {
    "title": "Titre automatisé",
    "content": "Contenu généré automatiquement via script Python.",
    "status": "publish"
}

response = requests.post(post_url, headers=headers, json=post_data)
print(response.status_code)
print(response.json())
