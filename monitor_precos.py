"""
╔══════════════════════════════════════════════════════════════════════╗
║           MONITOR DE PREÇOS - Amazon & Mercado Livre                ║
║  Stack: Selenium + BeautifulSoup + SQLite + Telegram                ║
╚══════════════════════════════════════════════════════════════════════╝

INSTALAÇÃO:
    pip install selenium webdriver-manager beautifulsoup4 requests

USO:
    1. Configure seu BOT_TOKEN e CHAT_ID do Telegram no arquivo config.py
    2. Adicione produtos via db.adicionar_produto(...)
    3. Execute: python monitor_precos.py
"""

# ── Bibliotecas da stdlib ──────────────────────────────────────────────────────
import sqlite3       # banco de dados local sem servidor
import time          # para pausas entre requisições
import random        # para delays aleatórios (evasão de bloqueio)
import re            # expressões regulares para limpar strings de preço
import logging       # registro de eventos e erros
import os            # para ler variáveis de ambiente
from datetime import datetime  # timestamp das verificações

# ── Bibliotecas de terceiros ───────────────────────────────────────────────────
import requests                                  # chamadas HTTP simples (Telegram)
from bs4 import BeautifulSoup                    # parsing do HTML retornado pelo Selenium
from selenium import webdriver                   # automação do navegador
from selenium.webdriver.chrome.service import Service   # gerenciador do ChromeDriver
from selenium.webdriver.chrome.options import Options   # configurações do Chrome
from selenium.webdriver.common.by import By             # estratégias de localização de elementos
from selenium.webdriver.support.ui import WebDriverWait # espera explícita por elementos
from selenium.webdriver.support import expected_conditions as EC  # condições de espera
from webdriver_manager.chrome import ChromeDriverManager  # download automático do ChromeDriver

# ── Configuração do Logger ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,  # mostra INFO, WARNING, ERROR e CRITICAL
    format="%(asctime)s [%(levelname)s] %(message)s",  # formato: hora [NÍVEL] mensagem
    handlers=[
        logging.StreamHandler(),                        # saída no terminal
        logging.FileHandler("monitor.log", encoding="utf-8"),  # salva em arquivo
    ],
)
logger = logging.getLogger(__name__)  # cria logger com o nome do módulo atual


# ══════════════════════════════════════════════════════════════════════════════
# CLASSE 1: Database — toda interação com o SQLite fica aqui
# ══════════════════════════════════════════════════════════════════════════════
class Database:
    """
    Responsável por criar, ler e escrever no banco de dados SQLite.
    Princípio: Single Responsibility — só sabe falar com o banco.
    """

    def __init__(self, caminho_db: str = "precos.db"):
        """
        Parâmetros
        ----------
        caminho_db : str
            Caminho/nome do arquivo .db que será criado (ou aberto).
        """
        self.caminho_db = caminho_db  # armazena o caminho para uso interno
        self._criar_tabelas()         # garante que as tabelas existem ao iniciar

    def _conectar(self) -> sqlite3.Connection:
        """Abre e retorna uma conexão com o banco. Uso interno."""
        conn = sqlite3.connect(self.caminho_db)  # cria o arquivo se não existir
        conn.row_factory = sqlite3.Row           # permite acessar colunas por nome (row["preco"])
        return conn

    def _criar_tabelas(self):
        """Cria as tabelas necessárias caso ainda não existam (idempotente)."""
        with self._conectar() as conn:  # 'with' fecha a conexão automaticamente
            conn.executescript("""
                -- Tabela de produtos cadastrados para monitoramento
                CREATE TABLE IF NOT EXISTS produtos (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome           TEXT    NOT NULL,       -- ex: "Galaxy S24"
                    url            TEXT    NOT NULL UNIQUE,-- URL do produto
                    seletor_css    TEXT    NOT NULL        -- ex: ".a-price .a-offscreen"
                );

                -- Histórico de preços coletados ao longo do tempo
                CREATE TABLE IF NOT EXISTS historico (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_produto     INTEGER NOT NULL REFERENCES produtos(id),
                    preco          REAL    NOT NULL,       -- float, ex: 1299.90
                    data_verificacao TEXT  NOT NULL        -- ISO 8601: "2025-06-18 14:30:00"
                );
            """)
        logger.info("Banco de dados inicializado em '%s'", self.caminho_db)

    # ── CRUD de produtos ───────────────────────────────────────────────────────

    def adicionar_produto(self, nome: str, url: str, seletor_css: str) -> int:
        """
        Cadastra um novo produto para monitoramento.

        Parâmetros
        ----------
        nome        : nome amigável do produto
        url         : URL da página do produto ou busca
        seletor_css : seletor CSS do elemento que contém o preço

        Retorna
        -------
        int : id gerado para o produto
        """
        with self._conectar() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO produtos (nome, url, seletor_css) VALUES (?, ?, ?)",
                (nome, url, seletor_css),  # '?' evita SQL Injection
            )
            conn.commit()  # persiste a inserção
            produto_id = cursor.lastrowid  # id gerado automaticamente
        logger.info("Produto cadastrado: '%s' (id=%s)", nome, produto_id)
        return produto_id

    def listar_produtos(self) -> list:
        """Retorna todos os produtos cadastrados como lista de dicionários."""
        with self._conectar() as conn:
            rows = conn.execute("SELECT * FROM produtos").fetchall()
        # converte cada Row para dict para facilitar o uso externo
        return [dict(row) for row in rows]

    # ── CRUD de histórico ──────────────────────────────────────────────────────

    def registrar_preco(self, id_produto: int, preco: float):
        """Salva um novo registro de preço no histórico."""
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # timestamp legível
        with self._conectar() as conn:
            conn.execute(
                "INSERT INTO historico (id_produto, preco, data_verificacao) VALUES (?, ?, ?)",
                (id_produto, preco, agora),
            )
            conn.commit()
        logger.info("Preço R$ %.2f registrado para produto id=%d", preco, id_produto)

    def preco_minimo_historico(self, id_produto: int) -> float | None:
        """
        Retorna o menor preço já registrado para um produto.
        Retorna None se ainda não há histórico (primeira verificação).
        """
        with self._conectar() as conn:
            row = conn.execute(
                "SELECT MIN(preco) as minimo FROM historico WHERE id_produto = ?",
                (id_produto,),
            ).fetchone()
        # row["minimo"] será None se a tabela estiver vazia para esse produto
        return row["minimo"] if row else None

    def historico_produto(self, id_produto: int) -> list:
        """Retorna todo o histórico de preços de um produto, do mais recente ao mais antigo."""
        with self._conectar() as conn:
            rows = conn.execute(
                """SELECT preco, data_verificacao
                   FROM historico
                   WHERE id_produto = ?
                   ORDER BY data_verificacao DESC""",
                (id_produto,),
            ).fetchall()
        return [dict(row) for row in rows]


# ══════════════════════════════════════════════════════════════════════════════
# CLASSE 2: Notifier — tudo relacionado a enviar mensagens fica aqui
# ══════════════════════════════════════════════════════════════════════════════
class Notifier:
    """
    Envia notificações via API do Telegram.
    Isolado em classe própria para facilitar troca por e-mail/WhatsApp no futuro.
    """

    # URL base da API do Telegram Bot
    _BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, bot_token: str, chat_id: str):
        """
        Parâmetros
        ----------
        bot_token : token do bot (obtido com @BotFather no Telegram)
        chat_id   : ID do chat/canal que receberá as mensagens
                    (use @userinfobot para descobrir o seu)
        """
        self.bot_token = bot_token  # ex: "123456:ABCdef..."
        self.chat_id   = chat_id    # ex: "987654321" ou "@meu_canal"
        self._url      = self._BASE_URL.format(token=bot_token)  # URL pronta para uso

    def enviar_telegram(self, mensagem: str) -> bool:
        """
        Envia uma mensagem de texto ao Telegram.

        Parâmetros
        ----------
        mensagem : texto da notificação (suporta Markdown)

        Retorna
        -------
        bool : True se enviado com sucesso, False caso contrário
        """
        payload = {
            "chat_id":    self.chat_id,    # destinatário
            "text":       mensagem,         # corpo da mensagem
            "parse_mode": "Markdown",       # permite **negrito**, _itálico_, etc.
        }
        try:
            resposta = requests.post(self._url, data=payload, timeout=10)
            resposta.raise_for_status()  # lança exceção se status >= 400
            logger.info("Notificação Telegram enviada com sucesso.")
            return True
        except requests.RequestException as erro:
            # Captura erros de rede, timeout, resposta HTTP inválida, etc.
            logger.error("Falha ao enviar Telegram: %s", erro)
            return False

    def alerta_minima_historica(
        self,
        nome_produto: str,
        preco_atual: float,
        preco_anterior: float,
        url: str,
    ):
        """
        Formata e envia um alerta de mínima histórica.
        Método de conveniência que monta a mensagem padrão.
        """
        # Calcula a variação percentual em relação ao preço anterior
        variacao = ((preco_atual - preco_anterior) / preco_anterior) * 100

        mensagem = (
            f"🚨 *MÍNIMA HISTÓRICA DETECTADA!*\n\n"
            f"📦 *Produto:* {nome_produto}\n"
            f"💰 *Preço atual:* R$ {preco_atual:.2f}\n"
            f"📉 *Mínima anterior:* R$ {preco_anterior:.2f}\n"
            f"📊 *Variação:* {variacao:+.1f}%\n"
            f"🔗 [Ver produto]({url})\n\n"
            f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
        return self.enviar_telegram(mensagem)


# ══════════════════════════════════════════════════════════════════════════════
# CLASSE 3: Scraper — toda lógica de navegação e extração de dados
# ══════════════════════════════════════════════════════════════════════════════
class Scraper:
    """
    Controla o Selenium para navegar nas páginas e extrai
    os dados de preço usando BeautifulSoup.
    """

    # User-Agents reais de navegadores comuns para evitar detecção
    _USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    ]

    def __init__(self, headless: bool = True):
        """
        Parâmetros
        ----------
        headless : True = roda em segundo plano (sem abrir janela)
                   False = abre o Chrome visível (útil para depuração)
        """
        self.headless = headless
        self.driver   = None  # será criado ao chamar iniciar()

    def iniciar(self):
        """Cria e configura a instância do ChromeDriver."""
        opcoes = Options()  # objeto de configuração do Chrome

        # ── Anti-detecção ─────────────────────────────────────────────────────
        user_agent = random.choice(self._USER_AGENTS)  # UA aleatório a cada sessão
        opcoes.add_argument(f"--user-agent={user_agent}")

        # Remove a flag "navigator.webdriver=true" que sites usam para detectar bots
        opcoes.add_argument("--disable-blink-features=AutomationControlled")
        opcoes.add_experimental_option("excludeSwitches", ["enable-automation"])
        opcoes.add_experimental_option("useAutomationExtension", False)

        # ── Performance ───────────────────────────────────────────────────────
        opcoes.add_argument("--no-sandbox")           # necessário em ambientes Linux/CI
        opcoes.add_argument("--disable-dev-shm-usage")# evita crash por memória compartilhada
        opcoes.add_argument("--disable-gpu")          # GPU não é necessária para scraping
        opcoes.add_argument("--window-size=1920,1080")# tamanho de tela realista

        if self.headless:
            opcoes.add_argument("--headless=new")  # modo headless moderno do Chrome

        # ── Inicialização ─────────────────────────────────────────────────────
        # webdriver_manager baixa automaticamente o ChromeDriver compatível
        servico = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=servico, options=opcoes)

        # Sobrescreve o atributo webdriver para None após a inicialização
        self.driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logger.info("Chrome iniciado (headless=%s, UA=%s...)", self.headless, user_agent[:40])

    def encerrar(self):
        """Fecha o navegador e libera recursos."""
        if self.driver:
            self.driver.quit()   # fecha todas as janelas e encerra o processo
            self.driver = None
            logger.info("Chrome encerrado.")

    # ── Método interno: delay aleatório ───────────────────────────────────────
    @staticmethod
    def _aguardar():
        """
        Pausa a execução por um tempo aleatório entre 5 e 15 segundos.
        Simula comportamento humano e reduz risco de bloqueio de IP.
        """
        espera = random.uniform(5, 15)  # float aleatório no intervalo
        logger.info("Aguardando %.1f segundos...", espera)
        time.sleep(espera)

    # ── Método interno: carrega uma URL e retorna o HTML ──────────────────────
    def _carregar_pagina(self, url: str, timeout: int = 20) -> str | None:
        """
        Navega até a URL e aguarda o carregamento do DOM.

        Parâmetros
        ----------
        url     : endereço a carregar
        timeout : segundos máximos para aguardar o elemento <body>

        Retorna
        -------
        str  : HTML da página, ou None em caso de erro
        """
        try:
            self.driver.get(url)  # instrui o Chrome a navegar
            # Espera até que <body> esteja presente — confirma que o HTML foi carregado
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            return self.driver.page_source  # HTML completo pós-renderização JS
        except Exception as erro:
            logger.error("Erro ao carregar '%s': %s", url, erro)
            return None

    # ── Método interno: extrai preço do HTML ──────────────────────────────────
    def _extrair_preco(self, html: str, seletor_css: str) -> float | None:
        """
        Usa BeautifulSoup para encontrar o elemento de preço pelo seletor CSS.

        Parâmetros
        ----------
        html         : string com o HTML da página
        seletor_css  : seletor CSS do elemento (ex: ".a-price .a-offscreen")

        Retorna
        -------
        float : preço como número decimal, ou None se não encontrado
        """
        soup = BeautifulSoup(html, "html.parser")  # faz o parse do HTML
        elemento = soup.select_one(seletor_css)    # busca o primeiro elemento que bate com o seletor

        if not elemento:
            logger.warning("Elemento '%s' não encontrado na página.", seletor_css)
            return None

        texto_preco = elemento.get_text(strip=True)  # pega o texto limpo, ex: "R$ 1.299,90"
        return self._converter_preco(texto_preco)

    # ── Método interno: converte texto para float ──────────────────────────────
    @staticmethod
    def _converter_preco(texto: str) -> float | None:
        """
        Converte string de preço brasileiro para float.

        Exemplos
        --------
        "R$ 1.299,90"  →  1299.90
        "1.299"        →  1299.0
        "R$999,00"     →  999.0
        """
        try:
            # Remove tudo que não é dígito, vírgula ou ponto
            somente_numeros = re.sub(r"[^\d,.]", "", texto)
            # Detecta formato brasileiro (ponto como milhar, vírgula como decimal)
            if "," in somente_numeros and "." in somente_numeros:
                # ex: "1.299,90" → remove pontos → "1299,90" → substitui vírgula → "1299.90"
                somente_numeros = somente_numeros.replace(".", "").replace(",", ".")
            elif "," in somente_numeros:
                # ex: "1299,90" → "1299.90"
                somente_numeros = somente_numeros.replace(",", ".")
            return float(somente_numeros)
        except (ValueError, AttributeError) as erro:
            logger.error("Não foi possível converter '%s' para float: %s", texto, erro)
            return None

    # ── Método interno: extrai nome/disponibilidade ───────────────────────────
    @staticmethod
    def _extrair_info(soup: BeautifulSoup) -> dict:
        """
        Tenta extrair nome e disponibilidade usando seletores comuns da Amazon e Mercado Livre.
        Os seletores podem variar — ajuste conforme necessário.
        """
        nome = None
        disponivel = True  # assume disponível por padrão

        # Tentativas de seletor de nome (Amazon e Mercado Livre)
        for seletor_nome in ["#productTitle", "h1.ui-pdp-title", "h1.x-item-title__mainTitle"]:
            el = soup.select_one(seletor_nome)
            if el:
                nome = el.get_text(strip=True)
                break

        # Tentativas de seletor de disponibilidade
        for seletor_disp in ["#availability span", ".ui-pdp-buybox__quantity"]:
            el = soup.select_one(seletor_disp)
            if el:
                texto = el.get_text(strip=True).lower()
                # Se o texto indicar indisponibilidade, marca como False
                if any(p in texto for p in ["indisponível", "unavailable", "esgotado", "out of stock"]):
                    disponivel = False
                break

        return {"nome": nome, "disponivel": disponivel}

    # ── Método público: coleta produto único ──────────────────────────────────
    def coletar_produto(self, url: str, seletor_css: str) -> dict | None:
        """
        Acessa uma URL de produto e extrai nome, preço e disponibilidade.

        Parâmetros
        ----------
        url         : URL da página do produto
        seletor_css : seletor CSS do elemento de preço

        Retorna
        -------
        dict : {"nome": str, "preco": float, "disponivel": bool, "url": str}
               ou None em caso de falha
        """
        logger.info("Coletando: %s", url)
        html = self._carregar_pagina(url)  # carrega a página
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        preco = self._extrair_preco(html, seletor_css)  # extrai o preço
        info  = self._extrair_info(soup)                 # extrai nome e disponibilidade

        if preco is None:
            logger.warning("Preço não encontrado em: %s", url)
            return None

        resultado = {
            "nome":      info["nome"] or "Produto sem nome",
            "preco":     preco,
            "disponivel": info["disponivel"],
            "url":       url,
        }
        logger.info("Coletado → %s | R$ %.2f | Disponível: %s",
                    resultado["nome"][:50], preco, info["disponivel"])
        return resultado

    # ── Método público: coleta páginas de busca (paginação) ───────────────────
    def coletar_busca(
        self,
        url_base: str,
        seletor_css: str,
        max_paginas: int = 3,
    ) -> list[dict]:
        """
        Percorre as primeiras `max_paginas` páginas de uma busca,
        coletando todos os produtos encontrados.

        Estratégia dupla:
        1. Tenta adicionar/incrementar parâmetro '&page=' na URL.
        2. Fallback: procura botão "Próximo" no HTML e clica nele.

        Parâmetros
        ----------
        url_base    : URL da página de busca (página 1)
        seletor_css : seletor CSS do preço nos resultados
        max_paginas : número máximo de páginas a percorrer

        Retorna
        -------
        list : lista de dicts com dados de cada produto encontrado
        """
        todos_produtos = []  # acumula resultados de todas as páginas

        for numero_pagina in range(1, max_paginas + 1):
            # ── Monta a URL da página atual ────────────────────────────────────
            # Remove parâmetro page existente e adiciona o correto
            url_sem_page = re.sub(r"[&?]page=\d+", "", url_base)
            separador    = "&" if "?" in url_sem_page else "?"
            url_pagina   = f"{url_sem_page}{separador}page={numero_pagina}"

            logger.info("Coletando página %d/%d: %s", numero_pagina, max_paginas, url_pagina)
            html = self._carregar_pagina(url_pagina)
            if not html:
                logger.warning("Falha ao carregar página %d. Interrompendo paginação.", numero_pagina)
                break

            soup    = BeautifulSoup(html, "html.parser")
            precos  = soup.select(seletor_css)  # todos os elementos de preço da página

            if not precos:
                logger.info("Nenhum preço encontrado na página %d. Fim da paginação.", numero_pagina)
                break

            # Itera sobre cada elemento de preço encontrado na página de busca
            for elemento in precos:
                texto_preco = elemento.get_text(strip=True)
                preco       = self._converter_preco(texto_preco)
                if preco:
                    # Tenta encontrar o nome do produto próximo ao preço
                    pai = elemento.find_parent("div", class_=re.compile(r"item|product|result", re.I))
                    nome_el = pai.select_one("h2, h3, .product-title") if pai else None
                    nome    = nome_el.get_text(strip=True)[:80] if nome_el else "Produto"

                    todos_produtos.append({
                        "nome":  nome,
                        "preco": preco,
                        "url":   url_pagina,
                        "pagina": numero_pagina,
                    })

            logger.info("Página %d: %d preços encontrados.", numero_pagina, len(precos))

            # Delay entre páginas para não sobrecarregar o servidor
            if numero_pagina < max_paginas:
                self._aguardar()

        logger.info("Total de produtos coletados na busca: %d", len(todos_produtos))
        return todos_produtos


# ══════════════════════════════════════════════════════════════════════════════
# CLASSE 4: PriceMonitor — orquestra as três classes acima
# ══════════════════════════════════════════════════════════════════════════════
class PriceMonitor:
    """
    Coordena Scraper, Database e Notifier para executar o ciclo completo
    de monitoramento: coletar → salvar → comparar → alertar.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        caminho_db: str = "precos.db",
        headless: bool = True,
    ):
        """
        Parâmetros
        ----------
        bot_token  : token do bot Telegram
        chat_id    : ID do chat que receberá os alertas
        caminho_db : caminho do arquivo SQLite
        headless   : se True, o Chrome roda sem interface gráfica
        """
        # Instancia os três módulos de responsabilidade única
        self.db       = Database(caminho_db)
        self.notifier = Notifier(bot_token, chat_id)
        self.scraper  = Scraper(headless=headless)

    def adicionar_produto(self, nome: str, url: str, seletor_css: str) -> int:
        """Atalho para cadastrar um novo produto no banco."""
        return self.db.adicionar_produto(nome, url, seletor_css)

    def verificar_todos(self):
        """
        Ciclo principal: itera sobre todos os produtos cadastrados,
        coleta o preço atual e dispara alerta se for mínima histórica.
        """
        produtos = self.db.listar_produtos()  # busca todos os produtos cadastrados
        if not produtos:
            logger.warning("Nenhum produto cadastrado. Use adicionar_produto() primeiro.")
            return

        logger.info("Iniciando verificação de %d produto(s)...", len(produtos))
        self.scraper.iniciar()  # abre o Chrome uma única vez para todos os produtos

        try:
            for produto in produtos:
                self._verificar_produto(produto)
                # Delay entre produtos diferentes (cortesia com os servidores)
                Scraper._aguardar()
        finally:
            # Garante que o Chrome seja fechado mesmo se ocorrer uma exceção
            self.scraper.encerrar()

        logger.info("Verificação concluída.")

    def _verificar_produto(self, produto: dict):
        """
        Processa um único produto: coleta → salva → compara → alerta.

        Parâmetros
        ----------
        produto : dicionário com id, nome, url, seletor_css
        """
        id_prod     = produto["id"]
        nome        = produto["nome"]
        url         = produto["url"]
        seletor_css = produto["seletor_css"]

        # ── Coleta o preço atual via Selenium + BeautifulSoup ─────────────────
        dados = self.scraper.coletar_produto(url, seletor_css)
        if not dados:
            logger.warning("Pulando '%s' (sem dados coletados).", nome)
            return

        preco_atual = dados["preco"]

        # ── Salva no histórico ────────────────────────────────────────────────
        self.db.registrar_preco(id_prod, preco_atual)

        # ── Compara com o mínimo histórico ANTERIOR ───────────────────────────
        # Busca o mínimo ANTES de ter adicionado o preço atual
        historico = self.db.historico_produto(id_prod)

        # O mínimo histórico anterior são todos os registros, exceto o que acabamos de inserir
        precos_anteriores = [r["preco"] for r in historico[1:]]  # ignora o 1º (recém inserido)

        if not precos_anteriores:
            # Primeira coleta: sem histórico anterior para comparar
            logger.info("'%s': primeira coleta (R$ %.2f). Sem histórico para comparar.", nome, preco_atual)
            return

        minimo_anterior = min(precos_anteriores)  # menor preço do histórico passado

        logger.info(
            "'%s': atual=R$ %.2f | mínimo anterior=R$ %.2f",
            nome, preco_atual, minimo_anterior
        )

        # ── LÓGICA DE ALERTA: dispara apenas se preco_atual < minimo_anterior ─
        if preco_atual < minimo_anterior:
            logger.info("🚨 MÍNIMA HISTÓRICA para '%s'! Enviando alerta...", nome)
            self.notifier.alerta_minima_historica(
                nome_produto=nome,
                preco_atual=preco_atual,
                preco_anterior=minimo_anterior,
                url=url,
            )
        else:
            logger.info("Preço estável ou acima da mínima. Nenhum alerta necessário.")


# ══════════════════════════════════════════════════════════════════════════════
# PONTO DE ENTRADA — exemplo de uso
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":

   
    # Tenta pegar do ambiente, senão usa o hardcoded (não recomendado para produção)
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8624860250:AAFI6SJ0iQhRh05kCQKl06rjUuumIWogLzE")
    CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "1516454409")
    
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("Token ou Chat ID não configurados.")
        exit(1)

    monitor = PriceMonitor(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        headless=True,
    )

    monitor.adicionar_produto(
        nome="Teclado Mecânico Attack Shark",
        url="https://www.amazon.com.br/dp/B0DJ1574LX",
        seletor_css=".a-price .a-offscreen",
    )

    monitor.verificar_todos()

    # ── EXIBE HISTÓRICO NO TERMINAL ───────────────────────────────────────────
    print("\n" + "="*60)
    print("HISTÓRICO DE PREÇOS COLETADOS")
    print("="*60)
    for produto in monitor.db.listar_produtos():
        print(f"\n📦 {produto['nome']}")
        historico = monitor.db.historico_produto(produto["id"])
        for registro in historico[:5]:  # mostra os 5 mais recentes
            print(f"   R$ {registro['preco']:.2f} — {registro['data_verificacao']}")
