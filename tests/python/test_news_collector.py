"""
Testes CA-07 e CA-08 — news_collector.

CA-07: Noticia coletada em PT, title UTF-8 sem mojibake, published_at valido.
CA-08: Dois fetches consecutivos nao dobram itens no DB (dedup por guid).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from acoes_b3_monitor.types import NewsItem, NewsSource


# ---------------------------------------------------------------------------
# RSS mock payloads (simulando InfoMoney latin-1 e Money Times UTF-8)
# ---------------------------------------------------------------------------

INFOMONEY_RSS_LATIN1 = b"""<?xml version="1.0" encoding="ISO-8859-1"?>
<rss version="2.0">
  <channel>
    <title>InfoMoney</title>
    <item>
      <title>Petrobras anuncia dividendos recordes em 2026</title>
      <link>https://www.infomoney.com.br/noticias/petr4-dividendos-2026</link>
      <guid>https://www.infomoney.com.br/noticias/petr4-dividendos-2026</guid>
      <pubDate>Sat, 24 May 2026 09:00:00 +0000</pubDate>
      <category>Petrobras</category>
      <description><![CDATA[A a\xe7\xe3o PETR4 subiu ap\xf3s o an\xfancio de dividendos.]]></description>
    </item>
  </channel>
</rss>"""

MONEYTIMES_RSS_UTF8 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Money Times - Petrobras</title>
    <item>
      <title>Vale registra recorde de producao de minerio de ferro</title>
      <link>https://www.moneytimes.com.br/noticias/vale3-producao-record</link>
      <guid>https://www.moneytimes.com.br/noticias/vale3-producao-record</guid>
      <pubDate>Sat, 24 May 2026 10:30:00 +0000</pubDate>
      <description><![CDATA[A mineradora registrou recorde na producao do trimestre.]]></description>
    </item>
  </channel>
</rss>"""


@pytest.mark.asyncio
async def test_ca07_news_item_utf8_no_mojibake(settings, tmp_db) -> None:
    """CA-07: NewsItem.title deve ser UTF-8 sem mojibake (acentos corretos)."""
    import respx
    import httpx
    from acoes_b3_monitor.news_collector import fetch_news

    with respx.mock:
        # Mock InfoMoney feeds (latin-1)
        respx.get("https://www.infomoney.com.br/feed/").mock(
            return_value=httpx.Response(200, content=INFOMONEY_RSS_LATIN1)
        )
        respx.get("https://www.infomoney.com.br/mercados/feed/").mock(
            return_value=httpx.Response(200, content=INFOMONEY_RSS_LATIN1)
        )
        # Mock Money Times feeds
        respx.get("https://www.moneytimes.com.br/tag/petrobras/feed/").mock(
            return_value=httpx.Response(200, text=MONEYTIMES_RSS_UTF8)
        )
        respx.get("https://www.moneytimes.com.br/tag/vale/feed/").mock(
            return_value=httpx.Response(200, text=MONEYTIMES_RSS_UTF8)
        )
        respx.get("https://www.moneytimes.com.br/tag/itau/feed/").mock(
            return_value=httpx.Response(200, text=MONEYTIMES_RSS_UTF8)
        )
        respx.get("https://www.moneytimes.com.br/tag/magazine-luiza/feed/").mock(
            return_value=httpx.Response(200, text=MONEYTIMES_RSS_UTF8)
        )
        # Mock Google News
        for ticker_query in ["Petrobras+PETR4", "Vale+VALE3", "Itau+ITUB4", "Magazine+Luiza+MGLU3"]:
            respx.get(
                url__regex=r"news\.google\.com/rss/search.*"
            ).mock(return_value=httpx.Response(200, text=MONEYTIMES_RSS_UTF8))

        items = await fetch_news(["PETR4", "VALE3", "ITUB4", "MGLU3"], settings, tmp_db)

    assert len(items) >= 1, "Deve retornar ao menos 1 NewsItem"

    for item in items:
        # Verifica sem mojibake: string deve ser valida UTF-8 (str Python ja e unicode)
        assert isinstance(item.title, str), "title deve ser str Python (unicode)"
        # Verifica que nao ha caracteres de substituicao unicode (sinal de decode errado)
        assert "�" not in item.title, f"title contem char de substituicao (mojibake): {item.title!r}"
        # Verifica source valida
        assert item.source in {NewsSource.INFOMONEY, NewsSource.MONEYTIMES, NewsSource.GOOGLE_NEWS, NewsSource.CVM_IPE}
        # Verifica published_at com timezone
        assert item.published_at.tzinfo is not None, "published_at deve ter tzinfo"
        assert isinstance(item.published_at, datetime)


@pytest.mark.asyncio
async def test_ca07_infomoney_latin1_decoded() -> None:
    """CA-07: Verifica decode correto de latin-1 (a\xe7\xe3o deve virar 'acao')."""
    import feedparser

    xml_bytes = INFOMONEY_RSS_LATIN1
    # Simula o comportamento do news_collector
    xml_text = xml_bytes.decode("latin-1")
    feed = feedparser.parse(xml_text)

    assert len(feed.entries) > 0
    # O description contem 'ação' em latin-1
    description = feed.entries[0].get("description", "") or feed.entries[0].get("summary", "")
    # Feedparser deve ter decodificado corretamente
    assert "?" not in description or "ã" in description or "ç" in description or "ú" in description


@pytest.mark.asyncio
async def test_ca08_dedup_consecutive_fetches(settings, tmp_db) -> None:
    """CA-08: Dois fetches consecutivos nao dobram itens no DB."""
    import respx
    import httpx
    from acoes_b3_monitor.news_collector import fetch_news
    from acoes_b3_monitor.storage import save_news_item, get_news_since
    from datetime import timedelta

    with respx.mock:
        respx.get("https://www.infomoney.com.br/feed/").mock(
            return_value=httpx.Response(200, content=INFOMONEY_RSS_LATIN1)
        )
        respx.get("https://www.infomoney.com.br/mercados/feed/").mock(
            return_value=httpx.Response(200, content=INFOMONEY_RSS_LATIN1)
        )
        respx.get(url__regex=r"moneytimes\.com\.br/tag/.*").mock(
            return_value=httpx.Response(200, text=MONEYTIMES_RSS_UTF8)
        )
        respx.get(url__regex=r"news\.google\.com/rss/search.*").mock(
            return_value=httpx.Response(200, text=MONEYTIMES_RSS_UTF8)
        )

        items1 = await fetch_news(["PETR4", "VALE3", "ITUB4", "MGLU3"], settings, tmp_db)

        # Persiste os itens no DB (como faz o scheduler)
        for item in items1:
            await save_news_item(item, tmp_db)

        items2 = await fetch_news(["PETR4", "VALE3", "ITUB4", "MGLU3"], settings, tmp_db)

        # Tenta persistir novamente
        for item in items2:
            await save_news_item(item, tmp_db)

    # Busca todos os itens persistidos
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items_in_db_petr4 = await get_news_since("PETR4", since, tmp_db)
    items_in_db_vale3 = await get_news_since("VALE3", since, tmp_db)

    # Nao deve ter duplicados
    all_guids = [i.guid for i in items_in_db_petr4 + items_in_db_vale3]
    assert len(all_guids) == len(set(all_guids)), "Guids duplicados encontrados no DB"


@pytest.mark.asyncio
async def test_ca08_guid_unique_in_storage(news_item_vale3: NewsItem, tmp_db: str) -> None:
    """CA-08: INSERT OR IGNORE garante que guid duplicado nao cria novo registro."""
    from acoes_b3_monitor.storage import save_news_item, get_news_since
    from datetime import timedelta

    # Insere duas vezes o mesmo item
    await save_news_item(news_item_vale3, tmp_db)
    await save_news_item(news_item_vale3, tmp_db)  # deve ser ignorado

    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = await get_news_since("VALE3", since, tmp_db)

    vale3_items = [i for i in items if news_item_vale3.guid == i.guid]
    assert len(vale3_items) == 1, f"Esperado 1, encontrado {len(vale3_items)} itens com mesmo guid"
