from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import sys
import logging

from anki.collection import Collection, SearchNode
from mcp.server.fastmcp import FastMCP
from mcp.types import Tool, Resource, Prompt
import anyio
from .japanese_utils import read_vocab_csv

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger('anki_mcp')

class AnkiMCPServer:
    def __init__(self, collection_path: str):
        logger.info(f"Initializing AnkiMCP server with collection path: {collection_path}")
        self.collection_path = collection_path
        self.mcp = FastMCP("Anki MCP Server")
        logger.info("Setting up resources...")
        self._setup_resources()
        logger.info("Setting up tools...")
        self._setup_tools()
        logger.info("Setting up prompts...")
        self._setup_prompts()
        logger.info("Server initialization complete")

    def _setup_resources(self):
        @self.mcp.resource("anki://decks")
        def list_decks() -> str:
            # This is working
            """List all available Anki decks"""
            logger.debug("Listing all decks")
            col = None
            try:
                col = Collection(self.collection_path)
                decks = col.decks.all()
                result = "\n".join(f"- {deck['name']}" for deck in decks)
                logger.debug(f"Found {len(decks)} decks")
                return result
            except Exception as e:
                logger.error(f"Error listing decks: {str(e)}", exc_info=True)
                raise
            finally:
                if col:
                    col.close()

        @self.mcp.resource("anki://deck/{deck_name}/cards")
        def list_deck_cards(deck_name: str) -> str:
            """List all cards in a specific deck"""
            logger.debug(f"Listing cards in deck: {deck_name}")
            col = None
            try:
                col = Collection(self.collection_path)
                deck_id = col.decks.id_for_name(deck_name)
                cards = col.find_cards(f"deck:{deck_name}")
                result = "\n".join(
                    f"- {col.get_card(card_id).question()}" for card_id in cards
                )
                logger.debug(f"Found {len(cards)} cards in deck {deck_name}")
                return result
            except Exception as e:
                logger.error(f"Error listing cards in deck {deck_name}: {str(e)}", exc_info=True)
                raise
            finally:
                if col:
                    col.close()

        @self.mcp.resource("anki://recent/reviewed")
        # This is working
        def list_recently_reviewed() -> str:
            """List cards reviewed in the last 24 hours"""
            logger.debug("Listing recently reviewed cards")
            col = None
            try:
                col = Collection(self.collection_path)
                cards = col.find_cards(f"rated:{1}")
                if not cards:
                    logger.debug("No cards reviewed in the last 24 hours")
                    return "No cards reviewed in the last 24 hours."
                
                result = []
                for card_id in cards:
                    card = col.get_card(card_id)
                    note = card.note()
                    deck_name = col.decks.name(card.did)
                    last_review = datetime.fromtimestamp(card.reps / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    
                    result.append(
                        f"Deck: {deck_name}\n"
                        f"Question: {card.question()}\n"
                        f"Answer: {card.answer()}\n"
                        f"Last reviewed: {last_review}\n"
                        f"Times reviewed: {card.reps}\n"
                        f"Ease: {card.factor/10}%\n"
                        f"---"
                    )
                
                logger.debug(f"Found {len(cards)} recently reviewed cards")
                return "\n".join(result)
            except Exception as e:
                logger.error(f"Error listing recently reviewed cards: {str(e)}", exc_info=True)
                raise
            finally:
                if col:
                    col.close()

        @self.mcp.resource("anki://recent/learned")
        def list_recently_learned() -> str:
            """List cards learned (graduated from new) in the last 24 hours"""
            logger.debug("Listing recently learned cards")
            col = None
            try:
                col = Collection(self.collection_path)
                cards = col.find_cards(f"rated:1 prop:ivl>0")
                if not cards:
                    logger.debug("No cards learned in the last 24 hours")
                    return "No cards learned in the last 24 hours."
                
                result = []
                for card_id in cards:
                    card = col.get_card(card_id)
                    note = card.note()
                    deck_name = col.decks.name(card.did)
                    learned_date = datetime.fromtimestamp(card.reps / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    
                    result.append(
                        f"Deck: {deck_name}\n"
                        f"Question: {card.question()}\n"
                        f"Answer: {card.answer()}\n"
                        f"Learned on: {learned_date}\n"
                        f"Current interval: {card.ivl} days\n"
                        f"---"
                    )
                
                logger.debug(f"Found {len(cards)} recently learned cards")
                return "\n".join(result)
            except Exception as e:
                logger.error(f"Error listing recently learned cards: {str(e)}", exc_info=True)
                raise
            finally:
                if col:
                    col.close()

    def _setup_tools(self):
        @self.mcp.tool()
        def import_japanese_vocab(csv_path: str, deck_name: str, tags: str = None) -> str:
            """Import Japanese vocabulary from a CSV file into a specific deck.
            
            The CSV file should have the following columns:
            - Expression (Japanese word)
            - Reading (Furigana)
            - Meaning (English meaning)
            - Tags (optional, semicolon-separated)
            
            Args:
                csv_path: Path to CSV file containing vocabulary
                deck_name: Name of the deck to import into
                tags: Additional tags to add to all notes (comma-separated)
            """
            logger.debug(f"Starting import process for deck: {deck_name}")
            col = None
            try:
                col = Collection(self.collection_path)
                
                # Get the deck ID
                deck_id = col.decks.id_for_name(deck_name)
                if not deck_id:
                    logger.error(f"Deck '{deck_name}' not found")
                    return f"Error: Deck '{deck_name}' not found"
                
                # Get the Japanese note type
                notetype = col.models.by_name("Japanese (recognition)")
                if not notetype:
                    logger.error("Japanese (recognition) note type not found")
                    return "Error: Japanese (recognition) note type not found"
                
                # Process additional tags
                additional_tags = []
                if tags:
                    additional_tags = [tag.strip() for tag in tags.split(',')]
                
                # Get existing notes in the deck
                existing_notes = {}
                for cid in col.decks.cids(deck_id):
                    card = col.get_card(cid)
                    note = col.get_note(card.nid)
                    existing_notes[note.fields[0]] = note  # Use Expression field as key
                
                # Read and process the CSV file
                notes_added = 0
                notes_updated = 0
                notes_skipped = 0
                
                vocab_entries = read_vocab_csv(csv_path, additional_tags)
                
                for entry in vocab_entries:
                    # Check if note exists
                    if entry['expression'] in existing_notes:
                        # Update existing note
                        note = existing_notes[entry['expression']]
                        note.fields = entry['fields']
                        note.tags = entry['tags']
                        notes_updated += 1
                    else:
                        # Create new note
                        note = col.new_note(notetype)
                        note.fields = entry['fields']
                        note.tags = entry['tags']
                        try:
                            col.add_note(note, deck_id)
                            notes_added += 1
                        except Exception as e:
                            logger.error(f"Error adding note '{entry['expression']}': {str(e)}")
                            notes_skipped += 1
                
                # Save changes
                col.save()
                
                result = f"Import complete:\nNotes added: {notes_added}\nNotes updated: {notes_updated}\nNotes skipped (errors): {notes_skipped}"
                logger.debug(result)
                return result
                
            except Exception as e:
                logger.error(f"Error importing vocabulary: {str(e)}", exc_info=True)
                raise
            finally:
                if col:
                    col.close()

        @self.mcp.tool()
        def add_card(deck_name: str, front: str, back: str) -> str:
            """Add a new card to a specified deck"""
            logger.debug(f"Adding new card to deck: {deck_name}")
            col = None
            try:
                col = Collection(self.collection_path)
                deck_id = col.decks.id_for_name(deck_name)
                model = col.models.by_name("Basic")
                note = col.new_note(model)
                note.fields[0] = front
                note.fields[1] = back
                col.add_note(note, deck_id)
                logger.debug(f"Successfully added card to deck {deck_name}")
                return f"Added new card to deck '{deck_name}'"
            except Exception as e:
                logger.error(f"Error adding card to deck {deck_name}: {str(e)}", exc_info=True)
                raise
            finally:
                if col:
                    col.close()

        @self.mcp.tool()
        def review_card(card_id: int, ease: int) -> str:
            """Review a card with a specific ease (1-4)"""
            logger.debug(f"Reviewing card {card_id} with ease {ease}")
            if not 1 <= ease <= 4:
                logger.error(f"Invalid ease value: {ease}")
                raise ValueError("Ease must be between 1 and 4")
            
            col = None
            try:
                col = Collection(self.collection_path)
                card = col.get_card(card_id)
                card.start_timer()
                col.sched.answer_card(card, ease)
                logger.debug(f"Successfully reviewed card {card_id}")
                return f"Card {card_id} reviewed with ease {ease}"
            except Exception as e:
                logger.error(f"Error reviewing card {card_id}: {str(e)}", exc_info=True)
                raise
            finally:
                if col:
                    col.close()

        @self.mcp.tool()
        def get_card_history(card_id: int) -> str:
            """Get the review history of a specific card"""
            logger.debug(f"Getting history for card {card_id}")
            col = None
            try:
                col = Collection(self.collection_path)
                card = col.get_card(card_id)
                # revlog = col.db.all(
                #     "select id, ease, ivl, factor, time, type from revlog where cid = ? order by id desc",
                #     card_id
                # )
                revlog = col.db.execute(
                    "select id, ease, ivl, factor, time, type from revlog order by id desc limit 5",
                )
                
                if not revlog:
                    logger.debug(f"No review history found for card {card_id}")
                    return f"No review history found for card {card_id}"
                
                result = [f"Review history for card {card_id}:"]
                for rev in revlog:
                    rev_date = datetime.fromtimestamp(rev[0] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    ease = rev[1]
                    interval = rev[2]
                    factor = rev[3] / 10
                    study_time = rev[4] / 1000
                    review_type = ["Learn", "Review", "Relearn", "Filtered", "Manual"][rev[5]]
                    
                    result.append(
                        f"Date: {rev_date}\n"
                        f"Type: {review_type}\n"
                        f"Ease: {ease}\n"
                        f"Interval: {interval} days\n"
                        f"Ease Factor: {factor}%\n"
                        f"Study Time: {study_time:.1f}s\n"
                        f"---"
                    )
                
                logger.debug(f"Found {len(revlog)} review entries for card {card_id}")
                return "\n".join(result)
            except Exception as e:
                logger.error(f"Error getting history for card {card_id}: {str(e)}", exc_info=True)
                raise
            finally:
                if col:
                    col.close()

        @self.mcp.tool()
        def get_deck_review_history(deck_name: str) -> str:
            """Get review history for all cards in a specific deck within the past 24 hours"""
            logger.debug(f"Getting review history for deck: {deck_name}")
            col = None
            try:
                col = Collection(self.collection_path)
                
                # Get deck ID
                deck_id = col.decks.id_for_name(deck_name)
                if not deck_id:
                    logger.error(f"Deck '{deck_name}' not found")
                    return f"Error: Deck '{deck_name}' not found"
                
                # Calculate timestamp for 24 hours ago (in milliseconds)
                cutoff = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)
                
                # Find cards reviewed in the last 24 hours in this deck
                query = f"deck:'{deck_name}' rated:1"
                card_ids = [int(cid) for cid in col.find_cards(query)]
                
                if not card_ids:
                    return f"No cards reviewed in deck '{deck_name}' in the past 24 hours"
                
                result = [f"Review history for deck '{deck_name}' in the past 24 hours:"]
                
                for card_id in card_ids:
                    card = col.get_card(card_id)
                    note = card.note()
                    
                    # Get review logs for this card
                    revlogs = col.db.list(
                        "select id from revlog where cid = ? and id > ? order by id desc",
                        card_id, cutoff
                    )
                    
                    if revlogs:
                        result.append(f"\nCard ID: {card_id}")
                        result.append(f"Question: {card.question()}")
                        result.append(f"Answer: {card.answer()}")
                        result.append("Reviews:")
                        
                        for rev_id in revlogs:
                            review = col.db.first(
                                "select ease, ivl, factor, time, type from revlog where id = ?",
                                rev_id
                            )
                            if review:
                                rev_date = datetime.fromtimestamp(rev_id / 1000).strftime('%Y-%m-%d %H:%M:%S')
                                ease = review[0]
                                interval = review[1]
                                factor = review[2] / 10
                                study_time = review[3] / 1000
                                review_type = ["Learn", "Review", "Relearn", "Filtered", "Manual"][review[4]]
                                
                                result.append(
                                    f"Date: {rev_date}\n"
                                    f"Type: {review_type}\n"
                                    f"Ease: {ease}\n"
                                    f"Interval: {interval} days\n"
                                    f"Ease Factor: {factor}%\n"
                                    f"Study Time: {study_time:.1f}s"
                                )
                        result.append("---")
                
                return "\n".join(result)
                
            except Exception as e:
                logger.error(f"Error getting review history for deck {deck_name}: {str(e)}", exc_info=True)
                raise
            finally:
                if col:
                    col.close()

        @self.mcp.tool()
        def update_notes_with_sentences(vocab_sentences: Dict[str, List[str]], deck_name: str = "Try! N3 Vocab") -> str:
            """Update existing Japanese notes with sample sentences.
            
            Args:
                vocab_sentences: Dictionary mapping vocabulary (expression) to list of sample sentences
                deck_name: Name of the deck to search in (defaults to "Try! N3 Vocab")
            
            Returns:
                Summary of Updates made
            """
            logger.debug(f"Starting note update process with sample sentences for {len(vocab_sentences)} words in deck '{deck_name}'")
            logger.debug(f"Vocabulary items: {list(vocab_sentences.keys())}")
            
            col = None
            try:
                col = Collection(self.collection_path)
                
                # Get the Japanese note type
                notetype = col.models.by_name("Japanese (recognition)")
                if not notetype:
                    logger.error("Japanese (recognition) note type not found")
                    return "Error: Japanese (recognition) note type not found"
                
                logger.debug(f"Found note type: {notetype['name']}")
                
                # Verify deck exists
                deck_id = col.decks.id_for_name(deck_name)
                if not deck_id:
                    logger.error(f"Deck '{deck_name}' not found")
                    return f"Error: Deck '{deck_name}' not found"
                
                logger.debug(f"Found deck: {deck_name} (id: {deck_id})")
                
                notes_updated = 0
                notes_not_found = []
                detailed_results = []
                
                for vocab, sentences in vocab_sentences.items():
                    logger.debug(f"\nProcessing vocabulary: {vocab}")
                    logger.debug(f"Sample sentences: {sentences}")
                    
                    # Search for notes with matching expression in the specific deck
                    search_query = f'deck:"{deck_name}" "note:Japanese (recognition)" "{vocab}"'
                    note_ids = col.find_notes(search_query)
                    logger.debug(f"Search query: {search_query}")
                    logger.debug(f"Found {len(note_ids)} matching notes")
                    
                    if not note_ids:
                        notes_not_found.append(vocab)
                        logger.warning(f"No notes found for vocabulary: {vocab}")
                        continue
                    
                    note_updated = False
                    for note_id in note_ids:
                        note = col.get_note(note_id)
                        logger.debug(f"Checking note {note_id}")
                        logger.debug(f"Note fields: {[f'Field {i}: {field}' for i, field in enumerate(note.fields)]}")
                        
                        # Check if this is the exact note we want (expression field matches)
                        if note.fields[0] == vocab:  # Expression field
                            logger.debug("Found exact matching note")
                            # Update reading field by appending sentences
                            current_reading = note.fields[2]  # Reading field
                            logger.debug(f"Current reading field: {current_reading}")
                            
                            new_sentences = []
                            for sentence in sentences:
                                if sentence not in current_reading:  # Avoid duplicate sentences
                                    new_sentences.append(sentence)
                            
                            if new_sentences:  # Only update if we have new sentences
                                logger.debug(f"Adding new sentences: {new_sentences}")
                                updated_reading = f"{current_reading}\n\n{'<br>- '.join(new_sentences)}"  # Added extra newline for better spacing
                                note.fields[2] = updated_reading
                                note.flush()
                                notes_updated += 1
                                note_updated = True
                                logger.debug(f"Updated reading field: {updated_reading}")
                            else:
                                logger.debug("No new sentences to add")
                    
                    status = "Updated" if note_updated else "No changes needed"
                    detailed_results.append(f"Vocabulary '{vocab}': {status}")
                
                # Save changes
                col.save()
                
                result = [f"Update complete: {notes_updated} notes updated in deck '{deck_name}'"]
                if notes_not_found:
                    result.append(f"Notes not found for: {', '.join(notes_not_found)}")
                result.append("\nDetailed results:")
                result.extend(detailed_results)
                
                logger.debug("\n".join(result))
                return "\n".join(result)
                
            except Exception as e:
                logger.error(f"Error updating notes with sentences: {str(e)}", exc_info=True)
                raise
            finally:
                if col:
                    col.close()

    def _setup_prompts(self):
        @self.mcp.prompt()
        def create_deck_prompt(deck_name: str) -> str:
            """Create a new deck prompt"""
            logger.debug(f"Creating prompt for deck: {deck_name}")
            return f"""Please help create a new deck named '{deck_name}'.
You can use the following tools:
- add_card: Add cards to the deck
- list_decks: View existing decks
"""

        @self.mcp.prompt()
        def review_history_prompt() -> str:
            """Get help analyzing review history"""
            logger.debug("Creating review history prompt")
            return """I can help you analyze your review history.
Available resources:
- anki://recent/reviewed: View cards reviewed in the last 24 hours
- anki://recent/learned: View cards learned in the last 24 hours

Available tools:
- get_card_history: Get detailed review history for a specific card
"""

        @self.mcp.prompt()
        def study_japanese_vocab_prompt() -> str:
            """Get help analyzing study history"""
            logger.debug("Creating study history prompt")
            return """Look through the review history vocab list in the last 24 hours.
            They are all Japanese words for N3 level. Create some fill-in-the-blank sentences 
            to help me memorize them. 

            Example Vocab: 
            - 食べる

            Example Sample Sentence:
            - おはよう。ご飯を＿＿＿か。

            Rules:
            0. List all the vocabs in the review history in its original form as options to choose from.
            1. Mix up the words in fill in the blanks
            2. For each new vocab, create 2 sentences.
            3. Mix up the order of the sentences
            4. Use only Japanese to reply and create the sentences. 
            5. Do not provide the answer to the user.

            Available resources:
            - anki://recent/studied: View cards studied in the last 24 hours.
            勉強が始めましょう！
            """

        @self.mcp.prompt()
        def vocab_sentences_json_prompt() -> str:
            """Get JSON dictionary mapping vocab to sample sentences"""
            logger.debug("Creating vocab sentences JSON prompt")
            return """Create a JSON dictionary that maps Japanese vocabulary to lists of sample sentences.

            Example Input Vocab:
            宝くじ
            息が止まる
            シロイルカ
            訪ねる
            海外研修

            Example Output Format:
            {
                "宝くじ": ["1億円が当たる宝くじを買いました。運がよければいいなと思います。"],
                "息が止まる": ["興奮しすぎて息が止まるかと思いました。"],
                "シロイルカ": ["水族館で白いシロイルカを見ました。とても可愛かったです。"],
                "訪ねる": ["友達の家を訪ねた時、お土産を持っていきました。"],
                "海外研修": ["会社は社員に海外研修の機会を与えています。"]
            }

            Rules:
            1. Return a valid JSON dictionary where each value is a list of strings
            2. Each key should be a vocabulary word
            3. Each value should be a list containing one or more natural Japanese sentences using that word
            4. Sentences should provide clear context for the word usage
            5. Use polite Japanese (です/ます form) for sentences
            6. Include only reviewed vocabulary from the last 24 hours

            Available resources:
            - anki://recent/reviewed: View cards reviewed in the last 24 hours
            """

    async def run_stdio(self):
        """Run the Anki MCP server using stdio transport"""
        logger.info("Starting server with stdio transport")
        try:
            await self.mcp.run_stdio_async()
        except Exception as e:
            logger.error(f"Error running server: {str(e)}", exc_info=True)
            raise

def main():
    import os
    
    # Get Anki collection path from environment or use default
    collection_path = os.getenv(
        "ANKI_COLLECTION_PATH",
        os.path.expanduser("~/Library/Application Support/Anki2/User 1/collection.anki2")
    )
    
    logger.info("Starting AnkiMCP server")
    server = AnkiMCPServer(collection_path)
    anyio.run(server.run_stdio)

if __name__ == "__main__":
    main()