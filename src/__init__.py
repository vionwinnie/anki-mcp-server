"""
Anki Model Context Protocol Server

This package provides a Model Context Protocol (MCP) server implementation
for interacting with Anki decks programmatically.
"""

from .server import AnkiMCPServer

__version__ = "0.1.0"
__all__ = ["AnkiMCPServer"]