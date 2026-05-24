"""
news_collector.py — Coleta de noticias de RSS (InfoMoney, Money Times, Google News) + CVM IPE.

Funcao principal:
  fetch_news(tickers, settings, db_path) -> list[NewsItem]

Detalhes criticos:
- InfoMoney: latin-1 (feedparser detecta, mas forcamos encoding)
- CVM IPE: ZIP -> CSV latin-1, dedup por Protocolo_Entrega
- Google News: <link> e redirect ofuscado; DEVE ser resolvido antes de persistir
- Money Times: UTF-8, tem feed por /tag/<empresa>/feed/
"""

from __future__ import annotations

import html
import io
import ipaddress
import logging
import re
import socket
import zipfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from .config import TICKER_TO_COMPANY_NAME, TICKER_TO_GOOGLE_QUERY, TICKER_TO_MONEYTIMES_SLUG
from .storage import is_cvm_protocol_seen, mark_cvm_protocol_seen
from .types import NewsItem, NewsSource, Settings

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; acoes-b3-monitor/1.0)"
CVM_BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS"

_CVM_ZIP_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024   # 50 MB
_CVM_ZIP_MAX_MEMBER_BYTES = 100 * 1024 * 1024     # 100 MB


def _is_private_host(hostname: str) -> bool:
    """
    Retorna True se o hostname resolve para IP privado, loopback ou link-local.
    Rejeita IPs RFC1918, 127.0.0.0/8, 169.254.0.0/16 (incl. IMDS) e ::1.
    """
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        pass  # hostname nao e IP literal; resolve via DNS

    try:
        resolved_ip = socket.getaddrinfo(hostname, None)[0][4][0]
        addr = ipaddress.ip_address(resolved_ip)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except Exception:
        return True  # em caso de falha de resolucao, rejeita por precaucao


def _validate_resolved_url(url: str) -> None:
    """
    Valida que a URL resolvida e segura:
    - esquema deve ser https
    - hostname nao pode resolver para IP privado/loopback/link-local

    Levanta ValueError se qualquer condicao for violada.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"SSRF guard: esquema nao permitido '{parsed.scheme}' em URL resolvida: {url!r}")
    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError(f"SSRF guard: hostname vazio em URL resolvida: {url!r}")
    if _is_private_host(hostname):
        raise ValueError(f"SSRF guard: hostname '{hostname}' resolve para IP interno em URL resolvida: {url!r}")

# Mapeamento ticker -> queries InfoMoney por keyword
TICKER_TO_INFOMONEY_KEYWORD: dict[str, str] = {
    "PETR4": "petrobras",
    "VALE3": "vale",
    "ITUB4": "itau",
    "MGLU3": "magazine luiza",
}

INFOMONEY_FEEDS = [
    "https://www.infomoney.com.br/feed/",
    "https://www.infomoney.com.br/mercados/feed/",
]


def _parse_pubdate(raw: str) -> datetime:
    """Parseia pubDate RFC822 para datetime UTC aware."""
    try:
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


def _clean_html(text: str | None) -> str | None:
    """Remove tags HTML e decodifica HTML entities."""
    if text is None:
        return None
    clean = re.sub(r"<[^>]+>", "", text)
    return html.unescape(clean).strip() or None


def _infer_tickers_from_text(text: str, tickers: list[str]) -> list[str]:
    """Infere quais tickers estao relacionados ao texto baseado em keywords."""
    text_lower = text.lower()
    found = []
    for t in tickers:
        keyword = TICKER_TO_INFOMONEY_KEYWORD.get(t, t.lower())
        if keyword in text_lower or t.lower() in text_lower:
            found.append(t)
    return found


async def _fetch_infomoney(tickers: list[str], client: httpx.AsyncClient) -> list[NewsItem]:
    """Coleta noticias do InfoMoney RSS. Encoding: latin-1."""
    items: list[NewsItem] = []
    seen_guids: set[str] = set()

    for feed_url in INFOMONEY_FEEDS:
        try:
            resp = await client.get(feed_url)
            resp.raise_for_status()
            # Forca latin-1 — InfoMoney serve latin-1 mesmo que cabecalho diga outro
            content_bytes = resp.content
            try:
                xml_text = content_bytes.decode("latin-1")
            except UnicodeDecodeError:
                xml_text = content_bytes.decode("utf-8", errors="replace")

            feed = feedparser.parse(xml_text)

            for entry in feed.entries:
                guid = entry.get("id") or entry.get("link", "")
                if not guid or guid in seen_guids:
                    continue

                title = _clean_html(entry.get("title", "")) or ""
                link = entry.get("link", "")
                pub_str = entry.get("published", "")
                published_at = _parse_pubdate(pub_str) if pub_str else datetime.now(tz=timezone.utc)
                body = _clean_html(entry.get("summary") or entry.get("description"))

                # Tenta inferir ticker via categories ou keywords
                categories = [c.get("term", "") for c in entry.get("tags", [])]
                cat_text = " ".join(categories).lower()
                related = _infer_tickers_from_text(title + " " + cat_text, tickers)

                if not related:
                    continue  # ignora noticias sem relacao com carteira

                seen_guids.add(guid)
                items.append(
                    NewsItem(
                        guid=f"infomoney:{guid}",
                        title=title,
                        source=NewsSource.INFOMONEY,
                        published_at=published_at,
                        url=link,
                        tickers=related,
                        body=body,
                        encoding_source="latin-1",
                    )
                )
        except Exception as e:
            logger.warning("Erro ao coletar InfoMoney (%s): %s", feed_url, e)

    return items


async def _fetch_moneytimes(tickers: list[str], client: httpx.AsyncClient) -> list[NewsItem]:
    """Coleta noticias do Money Times usando feeds por tag de empresa. Encoding: UTF-8."""
    items: list[NewsItem] = []

    for ticker in tickers:
        slug = TICKER_TO_MONEYTIMES_SLUG.get(ticker)
        if not slug:
            continue

        feed_url = f"https://www.moneytimes.com.br/tag/{slug}/feed/"
        try:
            resp = await client.get(feed_url)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

            for entry in feed.entries:
                guid = entry.get("id") or entry.get("link", "")
                if not guid:
                    continue

                title = _clean_html(entry.get("title", "")) or ""
                link = entry.get("link", "")
                pub_str = entry.get("published", "")
                published_at = _parse_pubdate(pub_str) if pub_str else datetime.now(tz=timezone.utc)
                body = _clean_html(entry.get("summary") or entry.get("description"))

                items.append(
                    NewsItem(
                        guid=f"moneytimes:{guid}",
                        title=title,
                        source=NewsSource.MONEYTIMES,
                        published_at=published_at,
                        url=link,
                        tickers=[ticker],
                        body=body,
                        encoding_source="utf-8",
                    )
                )
        except Exception as e:
            logger.warning("Erro ao coletar Money Times para %s: %s", ticker, e)

    return items


async def _resolve_google_redirect(url: str, _client: httpx.AsyncClient) -> str:
    """
    Segue redirect do Google News para obter URL real do artigo.
    Usa cliente httpx isolado (sem headers compartilhados) para evitar vazamento
    de headers em redirect (ver pitfall httpx-custom-header-forwarded-on-redirect).
    Valida esquema https e que host nao e IP interno (SSRF guard).
    Se falhar ou a URL resolvida nao passar na validacao, retorna a URL original.
    """
    if "news.google.com" not in url:
        return url
    try:
        # Cliente isolado — sem headers de auth que possam vazar em cross-host redirect
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as resolve_client:
            resp = await resolve_client.head(url)
            final_url = str(resp.url)
            if "news.google.com" not in final_url:
                _validate_resolved_url(final_url)
                return final_url
            # HEAD nao resolveu; tenta GET
            resp2 = await resolve_client.get(url)
            final_url2 = str(resp2.url)
            if "news.google.com" not in final_url2:
                _validate_resolved_url(final_url2)
                return final_url2
        return url
    except ValueError as e:
        logger.warning("SSRF guard rejeitou URL resolvida de Google News: %s", e)
        return url
    except Exception:
        return url


async def _fetch_google_news(tickers: list[str], client: httpx.AsyncClient) -> list[NewsItem]:
    """Coleta noticias do Google News RSS. Resolve redirect ofuscado."""
    items: list[NewsItem] = []

    for ticker in tickers:
        query = TICKER_TO_GOOGLE_QUERY.get(ticker, ticker)
        feed_url = (
            f"https://news.google.com/rss/search"
            f"?q={query.replace(' ', '+')}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
        )
        try:
            resp = await client.get(feed_url)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

            for entry in feed.entries:
                raw_link = entry.get("link", "")
                guid = entry.get("id") or raw_link
                if not guid:
                    continue

                title = _clean_html(entry.get("title", "")) or ""
                pub_str = entry.get("published", "")
                published_at = _parse_pubdate(pub_str) if pub_str else datetime.now(tz=timezone.utc)

                # Resolve redirect Google -> URL real
                real_url = await _resolve_google_redirect(raw_link, client)

                items.append(
                    NewsItem(
                        guid=f"googlenews:{guid}",
                        title=title,
                        source=NewsSource.GOOGLE_NEWS,
                        published_at=published_at,
                        url=real_url,
                        tickers=[ticker],
                        body=None,
                        encoding_source="utf-8",
                    )
                )
        except Exception as e:
            logger.warning("Erro ao coletar Google News para %s: %s", ticker, e)

    return items


async def fetch_cvm_ipe(tickers: list[str], db_path: str, client: httpx.AsyncClient) -> list[NewsItem]:
    """
    Baixa o ZIP CVM IPE do ano corrente, parseia CSV latin-1,
    filtra Fatos Relevantes das empresas monitoradas.
    Dedup por Protocolo_Entrega (marca no storage para evitar re-notificar).

    Protecoes de seguranca:
    - Rejeita se Content-Length > 50 MB antes de baixar
    - Rejeita nome de membro ZIP com '..' ou path absoluto (zip-slip)
    - Rejeita membro com file_size descompactado > 100 MB
    """
    import csv
    from datetime import date

    year = date.today().year
    zip_filename = f"ipe_cia_aberta_{year}.zip"
    zip_url = f"{CVM_BASE_URL}/{zip_filename}"

    try:
        # HEAD para checar Content-Length antes de baixar
        head_resp = await client.head(zip_url, timeout=15.0)
        content_length_str = head_resp.headers.get("content-length", "")
        if content_length_str:
            try:
                content_length = int(content_length_str)
                if content_length > _CVM_ZIP_MAX_DOWNLOAD_BYTES:
                    logger.warning(
                        "CVM IPE: ZIP recusado — Content-Length %d > limite %d bytes",
                        content_length,
                        _CVM_ZIP_MAX_DOWNLOAD_BYTES,
                    )
                    return []
            except ValueError:
                pass

        resp = await client.get(zip_url, timeout=60.0)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Erro ao baixar CVM IPE %s: %s", zip_url, e)
        return []

    # Verificacao pos-download do tamanho real
    if len(resp.content) > _CVM_ZIP_MAX_DOWNLOAD_BYTES:
        logger.warning(
            "CVM IPE: ZIP recusado pos-download — %d bytes > limite %d bytes",
            len(resp.content),
            _CVM_ZIP_MAX_DOWNLOAD_BYTES,
        )
        return []

    items: list[NewsItem] = []
    company_names = {t: TICKER_TO_COMPANY_NAME.get(t, "").upper() for t in tickers}

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
            if not csv_names:
                logger.warning("CVM IPE: ZIP sem CSV")
                return []

            csv_entry_name = csv_names[0]

            # Protecao zip-slip: rejeita nomes com '..' ou path absoluto
            if ".." in csv_entry_name or csv_entry_name.startswith("/"):
                logger.error(
                    "CVM IPE: nome de membro ZIP suspeito (zip-slip): %r", csv_entry_name
                )
                return []

            # Verifica tamanho descompactado antes de ler
            info = zf.getinfo(csv_entry_name)
            if info.file_size > _CVM_ZIP_MAX_MEMBER_BYTES:
                logger.error(
                    "CVM IPE: membro ZIP recusado — file_size descompactado %d > limite %d bytes",
                    info.file_size,
                    _CVM_ZIP_MAX_MEMBER_BYTES,
                )
                return []

            with zf.open(csv_entry_name) as f:
                # CSV e latin-1 com delimitador ;
                content = f.read().decode("latin-1", errors="replace")

        # Fecha o ZIP antes de fazer awaits (mistura de I/O sincrono e assincrono)
        reader = csv.DictReader(io.StringIO(content), delimiter=";")

        for row in reader:
            categoria = row.get("Categoria", "").strip()
            if categoria != "Fato Relevante":
                continue

            protocolo = row.get("Protocolo_Entrega", "").strip()
            if not protocolo:
                continue

            # Verifica se ja foi processado
            if await is_cvm_protocol_seen(protocolo, db_path):
                continue

            nome_companhia = row.get("Nome_Companhia", "").upper()
            related_tickers = [
                t for t, cn in company_names.items()
                if cn and cn in nome_companhia
            ]
            if not related_tickers:
                # Marca como visto mesmo sem ticker relacionado (evita reprocessar)
                await mark_cvm_protocol_seen(protocolo, db_path)
                continue

            assunto = row.get("Assunto", "").strip()
            data_entrega_str = row.get("Data_Entrega", "").strip()
            link_download = row.get("Link_Download", "").strip()

            try:
                # Data no formato YYYY-MM-DD
                data_entrega = datetime.strptime(data_entrega_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                data_entrega = datetime.now(tz=timezone.utc)

            guid = f"cvm_ipe:{protocolo}"
            await mark_cvm_protocol_seen(protocolo, db_path)

            items.append(
                NewsItem(
                    guid=guid,
                    title=assunto or f"Fato Relevante — {nome_companhia}",
                    source=NewsSource.CVM_IPE,
                    published_at=data_entrega,
                    url=link_download or zip_url,
                    tickers=related_tickers,
                    body=None,
                    cvm_protocolo=protocolo,
                    cvm_link_download=link_download or None,
                    encoding_source="latin-1",
                )
            )
    except Exception as e:
        logger.error("Erro ao parsear CVM IPE: %s", e)

    logger.info("CVM IPE: %d novos fatos relevantes encontrados", len(items))
    return items


async def fetch_news(
    tickers: list[str],
    settings: Settings,
    db_path: str,
) -> list[NewsItem]:
    """
    Coleta noticias de todas as fontes (InfoMoney, Money Times, Google News).
    CVM IPE e coletado separadamente via fetch_cvm_ipe (1x/dia no scheduler).
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": DEFAULT_USER_AGENT},
        timeout=15.0,
        follow_redirects=False,  # controlamos redirects manualmente no Google News
    ) as client:
        infomoney = await _fetch_infomoney(tickers, client)
        moneytimes = await _fetch_moneytimes(tickers, client)
        google = await _fetch_google_news(tickers, client)

    all_items = infomoney + moneytimes + google

    # Dedup por guid dentro do batch (antes de ir pro storage)
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in all_items:
        if item.guid not in seen:
            seen.add(item.guid)
            unique.append(item)

    logger.info(
        "fetch_news: %d itens coletados (%d infomoney, %d moneytimes, %d google)",
        len(unique),
        len(infomoney),
        len(moneytimes),
        len(google),
    )
    return unique
