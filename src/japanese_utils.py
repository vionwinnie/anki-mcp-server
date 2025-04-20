#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import csv
from typing import List, Dict, Tuple
import logging

logger = logging.getLogger('anki_mcp')

def is_kanji(char: str) -> bool:
    """Check if a character is a kanji."""
    return '\u4e00' <= char <= '\u9fff'

def is_kana(char: str) -> bool:
    """Check if a character is hiragana or katakana."""
    return ('\u3040' <= char <= '\u309f' or  # Hiragana
            '\u30a0' <= char <= '\u30ff')    # Katakana

def add_furigana(expression: str, reading: str) -> str:
    """Add furigana only to kanji characters in the expression.
    
    Example:
        expression: 食べる
        reading: たべる
        result: 食[た]べる
    """
    if not any(is_kanji(c) for c in expression):
        return reading
        
    result = []
    reading_pos = 0
    
    # Split the reading into kana segments
    kana_segments = []
    current_segment = []
    
    for char in reading:
        if is_kana(char):
            if current_segment:
                kana_segments.append(''.join(current_segment))
                current_segment = []
            kana_segments.append(char)
        else:
            current_segment.append(char)
    if current_segment:
        kana_segments.append(''.join(current_segment))
    
    # Match kana segments with expression
    kana_idx = 0
    for char in expression:
        if is_kanji(char):
            if kana_idx < len(kana_segments):
                result.append(f"{char}[{kana_segments[kana_idx]}]")
                kana_idx += 1
            else:
                result.append(char)
        else:
            result.append(char)
            if kana_idx < len(kana_segments) and char == kana_segments[kana_idx]:
                kana_idx += 1
    
    return ''.join(result)

def read_vocab_csv(csv_path: str, additional_tags: List[str] = None) -> List[Dict[str, str]]:
    """Read vocabulary from a CSV file and process it.
    
    Args:
        csv_path: Path to CSV file containing vocabulary
        additional_tags: List of additional tags to add to all notes
        
    Returns:
        List of dictionaries containing processed vocabulary entries
    """
    logger.debug(f"Reading vocabulary from CSV file: {csv_path}")
    vocab_entries = []
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Get the expression and reading
                expression = row.get('Expression', '').strip()
                reading = row.get('Reading', '').strip()
                
                # Format the reading field with furigana only for kanji
                reading_with_furigana = add_furigana(expression, reading)
                
                # Prepare fields
                fields = [
                    expression,                                    # Expression
                    row.get('Meaning', '').strip(),               # Meaning
                    reading_with_furigana,                        # Reading with furigana
                ]
                
                # Prepare tags
                note_tags = []
                csv_tags = row.get('Tags', '').strip()
                if csv_tags:
                    note_tags.extend([tag.strip() for tag in csv_tags.split(';')])
                if additional_tags:
                    note_tags.extend(additional_tags)
                
                vocab_entries.append({
                    'fields': fields,
                    'tags': note_tags,
                    'expression': expression  # Used as key for existing notes
                })
                
        logger.debug(f"Successfully read {len(vocab_entries)} vocabulary entries")
        return vocab_entries
        
    except Exception as e:
        logger.error(f"Error reading vocabulary CSV file: {str(e)}", exc_info=True)
        raise 