#!/usr/bin/env python3
"""
MCP Server for Modular RAG Knowledge Hub.

This is the main entry point for the MCP server that provides knowledge retrieval
capabilities through various tools.
"""

import sys
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from core.settings import load_settings, validate_settings
from mcp_server.server import run_server


def main():
    """Main entry point."""
    try:
        # Load and validate settings
        settings = load_settings()
        validate_settings(settings)

        # Run the MCP server
        run_server(settings)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
