from __future__ import annotations

from pathlib import Path

import streamlit as st


PALETTE = {
    "navy": "#062B49",
    "navy_2": "#083B63",
    "solar": "#F5A623",
    "solar_dark": "#D88900",
    "green": "#2E7D32",
    "green_soft": "#EAF5EC",
    "blue_soft": "#EAF2F8",
    "gray_text": "#3A3A3A",
    "muted": "#697386",
    "line": "#E5E7EB",
    "background": "#F7F9FC",
    "white": "#FFFFFF",
    "red": "#B42318",
}


ICONS = {
    "map": """
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
      <path d="M9 18L3.8 20.1C3.4 20.3 3 20 3 19.6V5.7C3 5.5 3.1 5.3 3.3 5.2L9 3L15 6L20.2 3.9C20.6 3.7 21 4 21 4.4V18.3C21 18.5 20.9 18.7 20.7 18.8L15 21L9 18Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M9 3V18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M15 6V21" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
    </svg>
    """,
    "settings": """
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 15.2A3.2 3.2 0 1 0 12 8.8a3.2 3.2 0 0 0 0 6.4Z" stroke="currentColor" stroke-width="1.8"/>
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1A2 2 0 0 1 4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1A2 2 0 0 1 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1A2 2 0 0 1 19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.1a2 2 0 0 1 0 4H21a1.7 1.7 0 0 0-1.6 1Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    """,
    "sun": """
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z" stroke="currentColor" stroke-width="1.8"/>
      <path d="M12 1.5v2.5M12 20v2.5M4.6 4.6l1.8 1.8M17.6 17.6l1.8 1.8M1.5 12h2.5M20 12h2.5M4.6 19.4l1.8-1.8M17.6 6.4l1.8-1.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
    </svg>
    """,
    "chart": """
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
      <path d="M4 19V5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M4 19H20" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M7 15l3-4 3 2 5-7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M18 6h-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M18 6v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
    </svg>
    """,
    "table": """
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.8"/>
      <path d="M3 10h18M9 4v16M15 4v16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
    </svg>
    """,
    "bolt": """
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
      <path d="M13 2L5 13h6l-1 9 9-13h-6l0-7Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
    </svg>
    """,
}


def load_css() -> None:
    css_path = Path(__file__).resolve().parents[1] / "assets" / "styles.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def icon(name: str) -> str:
    return ICONS.get(name, ICONS["chart"])


def app_header() -> None:
    st.markdown(
        f"""
        <div class="app-header">
            <div class="app-header-icon">{icon("sun")}</div>
            <div>
                <h1>Reto GDMTH: Ingeniería y Viabilidad Fotovoltaica</h1>
                <p>Motor de simulación para irradiancia POA, generación eléctrica quinceminutal y análisis energético.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str | None = None, icon_name: str = "chart") -> None:
    subtitle_html = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        f"""
        <div class="section-header">
            <div class="section-icon">{icon(icon_name)}</div>
            <div>
                <h2>{title}</h2>
                {subtitle_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def info_panel(title: str, body: str, icon_name: str = "settings") -> None:
    st.markdown(
        f"""
        <div class="info-panel">
            <div class="info-panel-icon">{icon(icon_name)}</div>
            <div>
                <h3>{title}</h3>
                <p>{body}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str, help_text: str | None = None) -> None:
    help_html = f"<span>{help_text}</span>" if help_text else ""
    st.markdown(
        f"""
        <div class="metric-card-custom">
            <p>{label}</p>
            <h3>{value}</h3>
            {help_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
