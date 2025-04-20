# Anki MCP Server

A Model Context Protocol server implementation for interacting with Anki decks programmatically. This server allows Language Models to interact with Anki through a standardized interface.

## Features

- List available decks
- View cards in decks
- Add new cards
- Review cards with spaced repetition

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/anki-mcp-server.git
cd anki-mcp-server
```

2. Install dependencies:
```bash
pip install -e .
```

## Usage

1. Make sure Anki is not running (to avoid database locks)

2. Set the path to your Anki collection (optional):
```bash
export ANKI_COLLECTION_PATH="/path/to/your/collection.anki2"
```

3. Run the server:
```bash
python -m anki_mcp.server
```

The server will start on `localhost:8000` by default.

## Available Resources

- `anki://decks` - List all available Anki decks
- `anki://deck/{deck_name}/cards` - List all cards in a specific deck

## Available Tools

- `add_card(deck_name: str, front: str, back: str)` - Add a new card to a deck
- `review_card(card_id: int, ease: int)` - Review a card with a specific ease (1-4)

## Available Prompts

- `create_deck_prompt(deck_name: str)` - Get help creating a new deck

## License

MIT License