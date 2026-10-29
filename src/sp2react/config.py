"""Configuration: one YAML file, secrets only through environment variables."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, field_validator


class ConfigError(RuntimeError):
    pass


class SharePointConfig(BaseModel):
    site_url: str = Field(..., description="Full URL of the site, e.g. https://sp.example.com/sites/SEA")
    auth: Literal["ntlm", "cookie", "bearer", "none"] = "ntlm"
    username_env: str = "SP_USERNAME"          # DOMAIN\\user for NTLM
    password_env: str = "SP_PASSWORD"
    cookie_env: str = "SP_COOKIE"              # e.g. "FedAuth=...; rtFa=..." copied from a signed-in browser
    token_env: str = "SP_TOKEN"                # bearer token (SharePoint Online / Entra)
    verify_ssl: Union[bool, str] = True        # True, False, or path to a corporate CA bundle
    timeout: int = 60
    sample_items: int = 200                    # rows exported per list (lookup values, seed data)
    extra_headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("site_url")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.rstrip("/")


class LLMConfig(BaseModel):
    provider: Literal["bridger", "openai", "azure_openai", "anthropic", "scripted"] = "bridger"
    api_format: Literal["anthropic", "openai"] = "anthropic"  # bridger only: which wire format Bridger serves Claude on
    base_url: Optional[str] = None             # bridger: http://host:port ; azure: https://<res>.openai.azure.com
    model: Optional[str] = None                # model id as the provider lists it (run `sp2react doctor`); azure uses `deployment`
    api_key_env: Optional[str] = None          # env var holding the key/token; omit if Bridger needs none
    deployment: Optional[str] = None           # azure_openai only
    api_version: str = "2024-10-21"            # azure_openai only
    temperature: float = 0.0
    max_tokens: int = 16000
    timeout: int = 600                         # seconds per model call
    json_mode: bool = True                     # send response_format=json_object where supported
    extra_headers: dict[str, str] = Field(default_factory=dict)
    verify_ssl: Union[bool, str] = True


class PipelineConfig(BaseModel):
    workspace: str = "./sp2react-work"         # extraction, inventory, spec, agent transcripts, state
    output: str = "./converted-app"            # generated React + FastAPI app
    max_concurrency: int = 4                   # parallel agent calls
    agent_retries: int = 2                     # re-asks per agent task when its output fails validation
    agent_timeout: int = 900                   # hard limit per agent task (seconds)
    max_fix_iterations: int = 5
    auto_approve: bool = False                 # skip the human gates (spec + screen approval)
    run_builds: bool = True                    # npm install/build + pytest on the generated app
    data_source: Literal["database", "sqlite", "sharepoint"] = "database"
    # database   = your existing database (MySQL / SQL Server / PostgreSQL) through a list->table mapping;
    #              no list items are ever read from SharePoint
    # sqlite     = sp2react migrates the list items into a SQLite copy (needs sharepoint item reads)
    # sharepoint = the generated API reads and writes the live lists


class DatabaseConfig(BaseModel):
    url_env: str = "SP2REACT_DB_URL"           # env var with a SQLAlchemy URL, e.g. mysql+pymysql://user:pass@host:3306/sea
    schema_name: Optional[str] = None          # database schema, if not the default
    mapping: str = "./db-mapping.json"         # list -> table / field -> column mapping (sp2react map-db drafts it)


class SecurityConfig(BaseModel):
    allowed_hosts: list[str] = Field(default_factory=list)   # extra hosts beyond the SharePoint site and model endpoint
    sharepoint_item_reads: Optional[bool] = None             # None: allowed only when data_source is sqlite


class Config(BaseModel):
    sharepoint: SharePointConfig
    llm: LLMConfig = Field(default_factory=LLMConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    @property
    def item_reads_allowed(self) -> bool:
        """Whether sp2react may read list ITEMS (business data) from SharePoint over HTTP."""
        if self.security.sharepoint_item_reads is not None:
            return self.security.sharepoint_item_reads
        return self.pipeline.data_source == "sqlite"

    @property
    def workspace(self) -> Path:
        return Path(self.pipeline.workspace).resolve()

    @property
    def output(self) -> Path:
        return Path(self.pipeline.output).resolve()


def secret(env_name: Optional[str], what: str, required: bool = True) -> Optional[str]:
    if not env_name:
        if required:
            raise ConfigError(f"No environment variable configured for {what}.")
        return None
    value = os.environ.get(env_name)
    if not value and required:
        raise ConfigError(f"Set the environment variable {env_name} ({what}).")
    return value


def load_config(path: Union[str, Path]) -> Config:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}. Run `sp2react init` to create one.")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    try:
        cfg = Config.model_validate(data)
    except Exception as e:  # pydantic ValidationError -> readable message
        raise ConfigError(f"Invalid config {p}:\n{e}") from e
    # Relative workspace/output paths are relative to the config file, not the cwd
    base = p.resolve().parent
    for attr in ("workspace", "output"):
        val = getattr(cfg.pipeline, attr)
        if not Path(val).is_absolute():
            setattr(cfg.pipeline, attr, str((base / val).resolve()))
    if not Path(cfg.database.mapping).is_absolute():
        cfg.database.mapping = str((base / cfg.database.mapping).resolve())
    return cfg


TEMPLATE = """\
# sp2react configuration. Secrets are read from environment variables, never stored here.
sharepoint:
  site_url: https://sharepoint.example.com/sites/SEA
  auth: ntlm                 # ntlm | cookie | bearer | none
  username_env: SP_USERNAME  # DOMAIN\\\\user  (ntlm)
  password_env: SP_PASSWORD  #               (ntlm)
  cookie_env: SP_COOKIE      # "FedAuth=...; rtFa=..." from a signed-in browser (cookie)
  token_env: SP_TOKEN        # bearer token (bearer)
  verify_ssl: true           # or a path to your corporate CA bundle
  sample_items: 200

llm:
  provider: bridger          # bridger | anthropic | openai | azure_openai
  api_format: anthropic      # how Bridger serves Claude: anthropic (/v1/messages) or openai (/v1/chat/completions)
  base_url: http://localhost:4141
  model: claude-sonnet-4     # exact Claude model id as Bridger lists it: run `sp2react doctor`
  api_key_env: BRIDGER_TOKEN # omit if Bridger needs no token
  # azure_openai: base_url: https://<resource>.openai.azure.com, deployment: <name>, api_key_env: AZURE_OPENAI_API_KEY
  # anthropic:    model: claude-sonnet-5-5, api_key_env: ANTHROPIC_API_KEY
  # openai:       base_url: https://api.openai.com/v1, model: <model>, api_key_env: OPENAI_API_KEY

pipeline:
  workspace: ./sp2react-work
  output: ./converted-app
  max_concurrency: 4
  agent_retries: 2
  agent_timeout: 900
  max_fix_iterations: 5
  auto_approve: false
  run_builds: true
  data_source: database      # database: your existing MySQL/SQL Server tables (no list items read over HTTP)
                             # sqlite: sp2react migrates the items itself | sharepoint: API uses the live lists

database:
  url_env: SP2REACT_DB_URL   # read from the environment, e.g.
                             #   mssql+pyodbc://@db-host/SEA?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes
                             #   mysql+pymysql://user:password@db-host:3306/sea
  # schema_name: dbo         # schema holding the migrated tables, if not the default
  mapping: ./db-mapping.json # drafted by `sp2react map-db`, reviewed by you

security:
  allowed_hosts: []          # every request is refused unless it goes to the SharePoint site or the model endpoint
  # sharepoint_item_reads: false   # default: false unless data_source is sqlite
"""
