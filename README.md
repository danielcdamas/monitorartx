# Monitor RTX 5080

Monitoramento de preços **em tempo real** de placas de vídeo NVIDIA **GeForce RTX 5080**
nas lojas **Terabyteshop**, **KaBuM!**, **Amazon Brasil** e **Pichau** — com painel web
que atualiza sozinho e destaca o melhor preço à vista/Pix do momento.

## Recursos

- 🎯 **Melhor preço agora** — menor preço à vista/Pix entre todas as lojas, com link direto.
- 🔄 **Atualização automática** — coleta a cada 3 minutos (configurável) e envio instantâneo
  ao navegador via Server-Sent Events (sem precisar recarregar a página).
- 📉 **Histórico de preços** — gráfico do menor preço por loja (24 h / 7 dias / 30 dias),
  persistido em SQLite.
- 🏪 **Status por loja** — mostra quando uma loja está fora do ar ou bloqueou a coleta,
  sem derrubar as demais.
- 🧹 **Filtro de produto** — considera apenas placas RTX 5080 avulsas (exclui water blocks,
  cabos, suportes, PCs montados e notebooks).

## Como rodar

Requer Python 3.11+.

```bash
pip install -r requirements.txt
python run.py            # abre em http://localhost:8000
```

Ou diretamente com uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 5
```

### Modo demonstração (sem rede)

Para ver o painel funcionando com lojas simuladas (preços fictícios que variam a cada ciclo):

```bash
MOCK_STORES=1 SCRAPE_INTERVAL_SECONDS=15 python run.py
```

### Diagnóstico dos scrapers

Roda cada scraper uma única vez e imprime o que encontrou (útil para verificar se a sua
rede/IP consegue acessar cada loja):

```bash
python -m app.check              # todas as lojas
python -m app.check kabum pichau # apenas algumas
```

## Configuração (variáveis de ambiente)

| Variável | Padrão | Descrição |
|---|---|---|
| `SCRAPE_INTERVAL_SECONDS` | `180` | Intervalo entre ciclos de coleta |
| `SCRAPER_TIMEOUT_SECONDS` | `90` | Timeout de cada loja por ciclo |
| `DB_PATH` | `prices.db` | Caminho do banco SQLite |
| `PORT` | `8000` | Porta do servidor (`python run.py`) |
| `MOCK_STORES` | — | `1` ativa lojas simuladas (demo/teste) |

## API

| Endpoint | Descrição |
|---|---|
| `GET /` | Painel web |
| `GET /api/offers` | Snapshot completo (ofertas ordenadas, melhor preço, status) |
| `GET /api/best` | Apenas a melhor oferta atual |
| `GET /api/history?days=7` | Menor preço por loja/hora (para o gráfico) |
| `GET /api/status` | Status da última coleta por loja |
| `POST /api/refresh` | Força um novo ciclo de coleta imediatamente |
| `GET /api/stream` | SSE — empurra um snapshot a cada ciclo |

## Como cada loja é coletada

| Loja | Estratégia primária | Fallback |
|---|---|---|
| KaBuM! | API pública de catálogo (`servicespub.prod.api.aws.grupokabum.com.br`) | JSON `__NEXT_DATA__` da página de busca |
| Pichau | GraphQL (Magento 2) em `/api/pichau` com campos padrão | JSON `__NEXT_DATA__` da página de busca |
| Terabyteshop | Parsing HTML da busca (cards de produto) | Página da categoria RTX série 50 |
| Amazon | Parsing HTML da página de busca | — |

As requisições usam cabeçalhos de navegador e cada loja falha de forma independente —
o status aparece no painel. **Atenção:** Terabyteshop e Amazon usam anti-bot agressivo;
em IPs de datacenter/VPN a coleta pode ser bloqueada (o painel mostra o motivo).
Rodando em rede residencial no Brasil os resultados são bem mais estáveis.

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Estrutura

```
app/
├── main.py          # API FastAPI + SSE + frontend estático
├── monitor.py       # loop de coleta + broadcast em tempo real
├── database.py      # SQLite: ofertas, histórico e status
├── models.py        # Offer / StoreStatus
├── check.py         # CLI de diagnóstico (python -m app.check)
├── scrapers/
│   ├── base.py      # HTTP, parse de preço BRL, filtro RTX 5080
│   ├── kabum.py     # API + __NEXT_DATA__
│   ├── pichau.py    # GraphQL + __NEXT_DATA__
│   ├── terabyte.py  # HTML (busca + categoria)
│   ├── amazon.py    # HTML (busca)
│   └── mock.py      # lojas simuladas (MOCK_STORES=1)
└── static/          # painel web (HTML/CSS/JS puros)
```

> Os preços exibidos são coletados automaticamente e podem divergir do checkout —
> confirme sempre o valor final na página da loja.
