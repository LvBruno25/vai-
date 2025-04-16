import yfinance as yf
import requests
import pandas as pd
import time
from datetime import datetime
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
from bs4 import BeautifulSoup
from telegram import Bot

MAX_OPTION_PRICE = 2.00
TELEGRAM_TOKEN = "SEU_TOKEN_AQUI"
CHAT_ID = "SEU_CHAT_ID_AQUI"
NEWSAPI_KEY = "SUA_NEWSAPI_KEY_AQUI"

tokenizer = AutoTokenizer.from_pretrained("./finbert")
model = AutoModelForSequenceClassification.from_pretrained("./finbert")

labels = ["negative", "neutral", "positive"]

def analisar_sentimento_finbert(texto):
    inputs = tokenizer(texto, return_tensors="pt", truncation=True)
    with torch.no_grad():
        outputs = model(**inputs)
        scores = torch.nn.functional.softmax(outputs.logits, dim=1)[0]
    return labels[scores.argmax()]

def converter_sentimento_score(sentimento):
    return 1 if sentimento == "positive" else 0.5 if sentimento == "neutral" else 0

def buscar_noticias_sentimento(ticker):
    url = f'https://newsapi.org/v2/everything?q={ticker}&sortBy=publishedAt&apiKey={NEWSAPI_KEY}&language=en'
    r = requests.get(url)
    artigos = r.json().get('articles', [])[:3]
    return [(a['title'], analisar_sentimento_finbert(a['title'])) for a in artigos]

def verificar_insider_buy(ticker):
    url = f"http://openinsider.com/screener?s={ticker}&o=&pl=&ph=&ll=&lh=&fd=30"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'html.parser')
    table = soup.find("table", class_="tinytable")
    if not table:
        return False
    for row in table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) > 5 and cols[5].text.strip() == "P - Purchase":
            return True
    return False

def calcular_score(opcoes, preco_acao, sentimento_score):
    if opcoes.empty:
        return opcoes
    max_vol = opcoes['volume'].replace(0, 1).max()
    opcoes['score_volume'] = opcoes['volume'] / max_vol
    opcoes['score_preco'] = 1 - (opcoes['lastPrice'] / preco_acao)
    opcoes['score_strike'] = 1 - abs((opcoes['strike'] - preco_acao) / preco_acao)
    opcoes['score_final'] = (
        opcoes['score_volume'] + 
        opcoes['score_preco'] * 2 + 
        opcoes['score_strike'] + 
        sentimento_score * 2
    )
    return opcoes

def buscar_opcoes_com_ranking(ticker, sentimento_score):
    stock = yf.Ticker(ticker)
    expirations = stock.options
    if not expirations:
        return pd.DataFrame(), pd.DataFrame(), False

    chain = stock.option_chain(expirations[0])
    preco_acao = stock.history(period='1d')['Close'].iloc[-1]

    # CALLs
    calls = chain.calls.copy()
    calls = calls[(calls['strike'] > preco_acao) & (calls['lastPrice'] < MAX_OPTION_PRICE)]
    calls = calcular_score(calls, preco_acao, sentimento_score)
    calls = calls.sort_values(by='score_final', ascending=False).head(3)

    # PUTs
    puts = chain.puts.copy()
    puts = puts[(puts['strike'] < preco_acao) & (puts['lastPrice'] < MAX_OPTION_PRICE)]
    puts = calcular_score(puts, preco_acao, sentimento_score)
    puts = puts.sort_values(by='score_final', ascending=False).head(3)

    insider_buy = verificar_insider_buy(ticker)
    if insider_buy:
        if not calls.empty:
            calls['score_final'] += 1
        if not puts.empty:
            puts['score_final'] += 1

    return calls, puts, insider_buy

def buscar_10_mais_ativos():
    return ["AAPL", "TSLA", "NVDA", "AMD", "PLTR", "CCL", "SOFI", "MARA", "RIOT", "F"]

def enviar_telegram(msg):
    bot = Bot(token=TELEGRAM_TOKEN)
    bot.send_message(chat_id=CHAT_ID, text=msg)

def montar_alerta_para(ticker):
    noticias = buscar_noticias_sentimento(ticker)
    sentimento_score = sum(converter_sentimento_score(s) for _, s in noticias) / len(noticias)
    calls, puts, insider = buscar_opcoes_com_ranking(ticker, sentimento_score)
    
    texto = f"📊 *Alerta de Opções - {ticker}*\n\n"

    if not calls.empty:
        texto += "🔼 *Melhores CALLs:*\n"
        for _, row in calls.iterrows():
            texto += f"📈 CALL {row['strike']} | Preço: ${row['lastPrice']:.2f} | Score: {row['score_final']:.2f} | Venc: {row['lastTradeDate'].date()}\n"

    if not puts.empty:
        texto += "\n🔽 *Melhores PUTs:*\n"
        for _, row in puts.iterrows():
            texto += f"📉 PUT {row['strike']} | Preço: ${row['lastPrice']:.2f} | Score: {row['score_final']:.2f} | Venc: {row['lastTradeDate'].date()}\n"

    texto += "\n🔍 Insider: Compra recente detectada\n" if insider else "\n🔍 Insider: Nenhuma compra recente\n"
    texto += "\n📰 *Notícias:*\n"
    for t, s in noticias:
        icone = "✅" if s == "positive" else "❌" if s == "negative" else "⚪"
        texto += f"- {t} ({icone} {s})\n"

    enviar_telegram(texto)

while True:
    hora_atual = datetime.utcnow().hour
    if 13 <= hora_atual <= 20:
        ativos = buscar_10_mais_ativos()
        for ativo in ativos:
            try:
                montar_alerta_para(ativo)
                time.sleep(10)
            except Exception as e:
                print(f"Erro ao analisar {ativo}: {e}")
        time.sleep(1800)
    else:
        print("Fora do horário de mercado. Aguardando...")
        time.sleep(600)
       # Comentando o loop principal temporariamente
# while True:
#     hora_atual = datetime.utcnow().hour
#     ...

# Teste de envio
enviar_telegram("✅ Robô funcionando! Teste de envio concluído com sucesso.")



