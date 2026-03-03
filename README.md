# 🛒 Price Monitor Brasil

> Monitor automático de preços para Amazon e Mercado Livre com alertas no Telegram.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python)
![Selenium](https://img.shields.io/badge/Selenium-4.x-green?style=for-the-badge&logo=selenium)
![SQLite](https://img.shields.io/badge/SQLite-Database-lightblue?style=for-the-badge&logo=sqlite)
![Telegram](https://img.shields.io/badge/Telegram-Bot-2CA5E0?style=for-the-badge&logo=telegram)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)

---

## 📌 O que esse projeto faz?

- Acessa automaticamente páginas de produtos na Amazon e Mercado Livre
- Coleta o preço atual usando Selenium + BeautifulSoup
- Salva o histórico de preços em um banco de dados SQLite local
- Envia alerta no Telegram **somente quando o preço atingir uma nova mínima histórica**

---

## 🖥️ Demonstração

```
2026-03-03 00:04:53 [INFO] 'Teclado Mecânico Attack Shark': primeira coleta (R$ 341.99)
2026-03-03 00:04:53 [INFO] Aguardando 13.6 segundos...
2026-03-03 00:05:09 [INFO] Chrome encerrado.
2026-03-03 00:05:09 [INFO] Verificação concluída.

════════════════════════════════════════
HISTÓRICO DE PREÇOS COLETADOS
════════════════════════════════════════
📦 Teclado Mecânico Attack Shark
   R$ 341.99 — 2026-03-03 00:04:53
```

---

## ⚙️ Pré-requisitos

- [Python 3.10+](https://python.org/downloads) — marque **"Add Python to PATH"** na instalação
- [Google Chrome](https://google.com/chrome)
- [VS Code](https://code.visualstudio.com) (recomendado)

---

## 📦 Instalação

**1. Clone o repositório:**
```bash
git clone https://github.com/seu-usuario/price-monitor-brasil.git
cd price-monitor-brasil
```

**2. Crie e ative o ambiente virtual:**
```bash
# Criar
python -m venv venv

# Ativar (Windows)
venv\Scripts\activate

# Ativar (macOS/Linux)
source venv/bin/activate
```

**3. Instale as dependências:**
```bash
pip install selenium webdriver-manager beautifulsoup4 requests
```

---

## 🤖 Configurando o Telegram

**1. Crie o bot:**
- Abra o Telegram e pesquise por **@BotFather**
- Envie `/newbot` e siga as instruções
- Copie o **token** gerado

**2. Descubra seu Chat ID:**
- Mande uma mensagem para o seu bot
- Acesse no navegador:
```
https://api.telegram.org/botSEU_TOKEN/getUpdates
```
- Copie o número do `"id"` dentro de `"chat"`

**3. Configure no código:**

Abra o `monitor_precos.py` e edite o final do arquivo:
```python
BOT_TOKEN = "seu_token_aqui"
CHAT_ID   = "seu_chat_id_aqui"
```

---

## 🚀 Como usar

**1. Adicione um produto para monitorar:**

Edite o final do `monitor_precos.py`:
```python
monitor.adicionar_produto(
    nome="Teclado Mecânico Attack Shark",
    url="https://www.amazon.com.br/dp/B0DJ1574LX",
    seletor_css=".a-price .a-offscreen",
)
```

**2. Rode o monitor:**
```bash
python monitor_precos.py
```

**3. Agende a execução automática (opcional):**

Windows — Agendador de Tarefas, ou Linux/macOS:
```bash
# Verifica a cada 6 horas
0 */6 * * * /caminho/para/venv/bin/python /caminho/para/monitor_precos.py
```

---

## 🔍 Como encontrar o seletor CSS

1. Abra a página do produto no Chrome
2. Clique com botão direito no **preço** → **"Inspecionar"**
3. Copie a classe CSS do elemento destacado
4. Teste no Console do DevTools:
```javascript
document.querySelector(".sua-classe").innerText
```

**Seletores testados:**

| Site | Seletor CSS |
|------|------------|
| Amazon BR | `.a-price .a-offscreen` |
| Mercado Livre | `.andes-money-amount__fraction` |

---

## 🗄️ Banco de Dados

O SQLite é criado automaticamente. Estrutura:

**Tabela `produtos`** — id, nome, url, seletor_css

**Tabela `historico`** — id_produto, preco, data_verificacao

---

## 🏗️ Arquitetura

```
PriceMonitor (orquestrador)
├── Database   → SQLite
├── Scraper    → Selenium + BeautifulSoup
└── Notifier   → API Telegram
```

---

## 📁 Arquivos do projeto

```
price-monitor/
├── monitor_precos.py   # código principal
├── teste_telegram.py   # testa a integração com Telegram
├── requirements.txt    # dependências
├── README.md           # documentação
├── precos.db           # banco de dados (gerado automaticamente)
└── monitor.log         # logs (gerado automaticamente)
```

---

## ⚠️ Boas práticas

- Monitore no máximo 2-3 produtos por vez para evitar bloqueios
- O alerta só dispara na **mínima histórica real** — sem spam
- Nunca suba o `precos.db` no GitHub (contém seus dados)
- Nunca suba seu token do Telegram no GitHub

---

## 📄 Licença

Distribuído sob a licença MIT. Veja o arquivo `LICENSE` para mais informações.

---

⭐ Se esse projeto te ajudou, deixa uma estrela no repositório!
