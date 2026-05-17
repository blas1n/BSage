"""bsage.mcp — Model Context Protocol server (stdio + Streamable HTTP).

This package hosts the real MCP protocol implementation plus the
``plugin_bridge`` adapter that exposes input plugins as MCP tools.

Two transports share one :class:`bsage.mcp.api.ToolRegistry`:

* ``stdio`` (:mod:`bsage.mcp.stdio`) — the protocol Claude Desktop uses.
* ``Streamable HTTP`` (:mod:`bsage.mcp.streamable_http`) — mounted at
  ``/mcp`` by the gateway, unified with the other three BSVibe products.
"""
