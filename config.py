from pydantic_settings import BaseSettings, SettingsConfigDict


class AriaSettings(BaseSettings):
    openai_api_key: str = ""
    aria_model: str = "gpt-4o-mini"

    # When true (default) ARIA never calls a real Jira/Confluence/Okta tenant —
    # it reads/writes local JSON stores under data/ so the assistant is
    # fully demo-able offline. Flip to false once real credentials are set below.
    aria_mock_mode: bool = True

    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""

    confluence_base_url: str = ""
    confluence_email: str = ""
    confluence_api_token: str = ""

    okta_domain: str = ""
    okta_api_token: str = ""

    aria_port: int = 7862

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = AriaSettings()
