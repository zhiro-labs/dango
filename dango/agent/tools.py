"""
Tools the agent can call, built from AgentSettings.

Optional dependencies (ddgs, sqlalchemy, website reader, ...) are imported
inside each factory so a disabled tool never costs an import.
"""

from .settings import AgentSettings, sanitize_name

WORKSPACE_ALLOWED: list[str] = ["read", "list", "search"]


def _make_search_tools():
    """Web search toolkit with multi-engine fallback and clean no-result handling.

    DuckDuckGoTools pins backend="duckduckgo"; when that one engine returns
    nothing (common for non-English queries) or rate-limits, ddgs raises
    DDGSException straight into the run log. backend="auto" rotates across
    engines (google, bing, brave, duckduckgo, ...), and a genuine no-result
    outcome is returned to the model as a plain message instead of an error.
    """
    from agno.tools.websearch import WebSearchTools
    from ddgs.exceptions import DDGSException

    class _DangoSearchTools(WebSearchTools):
        def web_search(self, query: str, max_results: int = 5) -> str:
            """Use this function to search the web for a query.

            Args:
                query(str): The query to search for.
                max_results (optional, default=5): The maximum number of results to return.

            Returns:
                The search results from the web.
            """
            try:
                return super().web_search(query, max_results)
            except DDGSException as e:
                return f"No search results: {e}"

        def search_news(self, query: str, max_results: int = 5) -> str:
            """Use this function to get the latest news from the web.

            Args:
                query(str): The query to search for.
                max_results (optional, default=5): The maximum number of results to return.

            Returns:
                The latest news from the web.
            """
            try:
                return super().search_news(query, max_results)
            except DDGSException as e:
                return f"No news results: {e}"

    return _DangoSearchTools(backend="auto")


def _make_brave_search_tool(api_key: str):
    """Brave Search API tool (https://api.search.brave.com).

    Implemented directly with requests instead of agno.tools.bravesearch:
    the latter requires the unmaintained `brave-search` package, whose broken
    httpx metadata cannot be resolved by uv.
    """
    import asyncio
    import json as _json
    import requests as _requests
    from agno.tools import tool

    async def _fn(query: str, max_results: int = 5,
                  country: str = "US", search_lang: str = "en") -> str:
        r = await asyncio.to_thread(
            _requests.get,
            "https://api.search.brave.com/res/v1/web/search",
            params={
                "q": query,
                "count": min(max_results, 20),
                "country": country,
                "search_lang": search_lang,
            },
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            timeout=15,
        )
        if r.status_code != 200:
            return f"Brave Search error (HTTP {r.status_code}): {r.text[:300]}"
        results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
            }
            for item in r.json().get("web", {}).get("results", [])
        ]
        if not results:
            return "No search results — try a different query."
        return _json.dumps(results, ensure_ascii=False, indent=2)

    return tool(
        name="brave_search",
        description=(
            "Search the web with the Brave Search API. "
            "Args: query (str), max_results (int, default 5, max 20), "
            "country (two-letter code, default 'US'), "
            "search_lang (language code, default 'en'; use e.g. 'zh-hant' for Traditional Chinese)."
        ),
    )(_fn)


def _make_website_tools():
    """Website toolkit with separate single-page and crawl tools.

    Agno's stock WebsiteTools.read_url uses WebsiteReader() defaults
    (max_depth=3, max_links=10), which spiders linked pages — one URL in a
    chat message can trigger dozens of slow follow-up requests. Splitting the
    two modes lets the model pick: read_url for the common "what does this
    page say" case, crawl_website when related pages are actually needed.
    """
    import json as _json
    from agno.knowledge.reader.website_reader import WebsiteReader
    from agno.tools import Toolkit

    class _DangoWebsiteTools(Toolkit):
        def __init__(self):
            super().__init__(
                name="website_tools",
                tools=[self.read_url, self.crawl_website],
            )

        def read_url(self, url: str) -> str:
            """Read a single web page and return its content. Fast — fetches
            only the given URL without following any links. Prefer this tool
            whenever one page is enough.

            :param url: The url of the web page to read.
            :return: Relevant documents from the page.
            """
            docs = WebsiteReader(max_depth=1, max_links=1).read(url=url)
            return _json.dumps([doc.to_dict() for doc in docs])

        def crawl_website(self, url: str) -> str:
            """Crawl a website starting from the given URL, following
            same-domain links a few pages deep. Slow (each page is fetched
            sequentially) — use only when a single page is not enough, e.g.
            gathering related articles or exploring a site's sections.

            :param url: The starting url to crawl.
            :return: Relevant documents from the crawled pages.
            """
            docs = WebsiteReader(max_depth=2, max_links=5).read(url=url)
            return _json.dumps([doc.to_dict() for doc in docs])

    return _DangoWebsiteTools()


def _make_api_tool(name: str, base_url: str, api_key: str, description: str = ""):
    """Build a uniquely-named HTTP tool for one custom API config."""
    import asyncio
    import requests as _requests
    from agno.tools import tool

    safe = sanitize_name(name, "api")
    tool_name = f"call_{safe}_api"
    base = base_url.rstrip("/")

    async def _fn(endpoint: str = "", method: str = "GET",
                  params: dict | None = None, json_body: dict | None = None,
                  extra_headers: dict | None = None) -> str:
        url = f"{base}/{endpoint.lstrip('/')}" if endpoint else base
        headers: dict = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if extra_headers:
            headers.update(extra_headers)
        r = await asyncio.to_thread(
            _requests.request, method, url,
            params=params, json=json_body, headers=headers, timeout=30,
        )
        return r.text

    base_desc = (
        f"Make an HTTP request to the {name} API (base URL: {base_url}). "
        "Auth is pre-configured. Leave endpoint empty to hit the base URL directly."
    )
    desc = f"{description} {base_desc}" if description else base_desc
    return tool(name=tool_name, description=desc)(_fn)


def _make_db_tools(name: str, db_url: str, description: str, model) -> list:
    """Tools of a read-only DatabaseContextProvider for one SQL database config.

    `model` is the provider's own sub-agent model (always the fast model).
    """
    try:
        from sqlalchemy import create_engine
        from agno.context.database import DatabaseContextProvider, DEFAULT_READ_INSTRUCTIONS
    except ImportError:
        print(f"⚠️  sqlalchemy not installed — SQL provider '{name}' skipped")
        return []

    safe = sanitize_name(name, "db")

    try:
        engine = create_engine(db_url)
    except Exception as e:
        print(f"⚠️  Cannot create SQL engine for '{name}': {e}")
        return []

    read_instructions = (
        f"This database is: {description}\n\n{DEFAULT_READ_INSTRUCTIONS}"
        if description
        else None
    )

    provider = DatabaseContextProvider(
        id=safe,
        name=name,
        sql_engine=engine,
        readonly_engine=engine,
        read_instructions=read_instructions,
        write=False,
        model=model,
    )
    return provider.get_tools()


def build_tools(settings: AgentSettings, fast_model) -> list:
    """Fresh tool instances for one agent, in a fixed order."""
    tools = []
    if settings.enable_workspace:
        from agno.tools.workspace import Workspace
        tools.append(Workspace(settings.workspace_root, allowed=WORKSPACE_ALLOWED))
    if settings.enable_duckduckgo:
        tools.append(_make_search_tools())
    if settings.enable_brave_search:
        if settings.brave_api_key:
            tools.append(_make_brave_search_tool(settings.brave_api_key))
        else:
            print("⚠️  ENABLE_BRAVE_SEARCH is on but BRAVE_API_KEY is not set — Brave Search disabled")
    if settings.enable_website_tools:
        tools.append(_make_website_tools())
    if settings.enable_custom_apis:
        for api_cfg in settings.custom_apis:
            tools.append(_make_api_tool(
                api_cfg.get("name", "api"),
                api_cfg.get("base_url", ""),
                api_cfg.get("api_key", ""),
                api_cfg.get("description", ""),
            ))
    if settings.enable_sql_databases:
        for db_cfg in settings.sql_databases:
            tools.extend(_make_db_tools(
                db_cfg.get("name", "db"),
                db_cfg.get("db_url", ""),
                db_cfg.get("description", ""),
                model=fast_model,
            ))

    # User-defined tools from custom/*.py (gitignored). Opt-in per function via
    # the @agent_tool / @command_and_tool decorators; absent dir → no-op.
    from ..extensions.loader import get_custom_tools, load_custom_modules
    load_custom_modules()
    tools.extend(get_custom_tools())

    return tools
