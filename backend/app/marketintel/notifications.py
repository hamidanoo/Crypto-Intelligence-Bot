"""Telegram formatters for Phase 7 alerts and news.

Messages are short, labelled with source and time,
and never describe a movement as an opportunity.
Unavailable values are shown as "Unavailable", never
as zero. Duplicate prevention reuses the Phase 4
CampaignNotification table via record_notification.
"""

import html
from datetime import timezone
from zoneinfo import ZoneInfo

PKT = ZoneInfo("Asia/Karachi")


def format_pkt(value) -> str | None:
    if value is None:
        return None
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(PKT).strftime("%Y-%m-%d %H:%M PKT")


def format_market_alert_message(alert) -> str:
    change = f"{alert.change_percent}%" if alert.change_percent is not None else "Unavailable"
    price = str(alert.current_price) if alert.current_price is not None else "Unavailable"
    return (
        f"📈 <b>Market alert: {html.escape(alert.alert_type)}</b>\n\n"
        f"{html.escape(alert.symbol)}\n"
        f"Price: {price}\n"
        f"Change: {change}\n"
        f"Source: Binance Spot\n"
        f"Triggered: {format_pkt(alert.triggered_at) or 'Unknown'}"
    )


def format_news_message(news) -> str:
    published = format_pkt(news.published_at) if news.published_at else "Not officially confirmed"
    url = html.escape(news.original_url)
    return (
        f"📰 <b>{html.escape(news.category)}</b>\n\n"
        f"{html.escape(news.headline)}\n\n"
        f"Publisher: {html.escape(news.publisher)}\n"
        f"Published: {published}\n"
        f'<a href="{url}">Read original</a>'
    )
