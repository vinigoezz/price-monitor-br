import requests

BOT_TOKEN = "8624860250:AAFI6SJ0iQhRh05kCQKl06rjUuumIWogLzE"
CHAT_ID   = "1516454409"

url = f"https://api.telegram.org/bot8624860250:AAFI6SJ0iQhRhO5kCQKl06rjUuumIWogLzE/sendMessage"

resposta = requests.post(url, data={
    "chat_id": CHAT_ID,
    "text": "✅ Integração funcionando! Monitor de preços ativo.",
    "parse_mode": "Markdown"
})

resultado = resposta.json()

if resultado.get("ok"):
    print("✅ Sucesso! Mensagem enviada ao Telegram.")
else:
    print("❌ Falha no envio.")
    print(f"Erro: {resultado.get('description', 'desconhecido')}")
