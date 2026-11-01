"""Read bridge configuration from process environment or Streamlit Cloud Secrets."""
import os


def setting(key, default="", *, secrets_store=None):
    value = os.environ.get(key)
    if value:
        return str(value).strip()
    if secrets_store is None:
        try:
            import streamlit as st
            secrets_store = st.secrets
        except Exception:
            return default
    try:
        value = secrets_store.get("driver_bridge", {}).get(key) or secrets_store.get(key)
    except Exception:
        return default
    return str(value).strip() if value else default


def configured():
    return bool(setting("PARKING_DRIVER_API_URL")
                and len(setting("PARKING_PUBLISH_TOKEN")) >= 32)


def _owner_app_connected(value):
    """Legacy flag parser retained for callers upgrading from the original page."""
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")
