"""
Anki integration module with deduplication using AnkiConnect API.

This module provides a client for interacting with Anki through the AnkiConnect plugin.
It handles card creation with automatic deduplication based on question content.

Requirements:
- AnkiConnect plugin must be installed and running in Anki
- Default AnkiConnect URL: http://localhost:8765

Note: Deck names can contain spaces (e.g., "AWS Cloud Practitioner").
      For hierarchical decks, use :: separator (e.g., "Learning::AWS Cloud Practitioner")
"""

import hashlib
import json
import requests
from typing import Optional, List, Dict, Any


class AnkiClient:
    """
    Client for interacting with Anki through the AnkiConnect API.

    This client provides methods to create decks, add cards with deduplication,
    and check for existing cards based on question content.

    Attributes:
        anki_url (str): The URL of the AnkiConnect API endpoint.
    """

    def __init__(self, anki_url: str = "http://localhost:8765"):
        """
        Initialize the AnkiClient.

        Args:
            anki_url (str): The URL of the AnkiConnect API.
                          Defaults to http://localhost:8765
        """
        self.anki_url = anki_url

    def _invoke(self, action: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        Internal method to invoke AnkiConnect API actions.

        Args:
            action (str): The AnkiConnect action to invoke
            params (Dict[str, Any], optional): Parameters for the action

        Returns:
            Any: The result from AnkiConnect API

        Raises:
            Exception: If the AnkiConnect request fails or returns an error
        """
        payload = {
            "action": action,
            "version": 6
        }

        if params is not None:
            payload["params"] = params

        try:
            response = requests.post(self.anki_url, json=payload)
            response.raise_for_status()

            result = response.json()

            if len(result) != 2:
                raise Exception("Response has an unexpected number of fields")

            if "error" not in result:
                raise Exception("Response is missing required error field")

            if "result" not in result:
                raise Exception("Response is missing required result field")

            if result["error"] is not None:
                raise Exception(f"AnkiConnect error: {result['error']}")

            return result["result"]

        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to connect to AnkiConnect at {self.anki_url}: {str(e)}")

    def generate_card_id(self, question: str) -> str:
        """
        Generate a unique card ID from a question using MD5 hash.

        The question is normalized (stripped and lowercased) before hashing
        to ensure consistent deduplication regardless of whitespace or case variations.

        Args:
            question (str): The question text to generate an ID for

        Returns:
            str: MD5 hash of the normalized question
        """
        # Normalize the question: strip whitespace and convert to lowercase
        normalized_question = question.strip().lower()

        # Generate MD5 hash
        hash_object = hashlib.md5(normalized_question.encode('utf-8'))
        return hash_object.hexdigest()

    def card_exists_in_anki(self, question: str) -> bool:
        """
        Check if a card with the given question already exists in Anki.

        This method searches for notes containing the card ID generated from
        the question. Cards are tagged with their unique card_id for deduplication.

        Args:
            question (str): The question text to check

        Returns:
            bool: True if a card with this question exists, False otherwise
        """
        card_id = self.generate_card_id(question)

        # Search for notes with the card_id tag
        query = f"tag:card_id:{card_id}"

        try:
            note_ids = self._invoke("findNotes", {"query": query})
            return len(note_ids) > 0
        except Exception as e:
            # If search fails, assume card doesn't exist to allow retry
            print(f"Warning: Failed to check if card exists: {str(e)}")
            return False

    def get_or_create_deck(self, deck_name: str) -> bool:
        """
        Ensure a deck exists in Anki, creating it if necessary.

        Deck names can contain spaces and special characters. Anki fully supports
        deck names like "AWS Cloud Practitioner" or hierarchical decks like
        "Learning::AWS Cloud Practitioner".

        Args:
            deck_name (str): Name of the deck to get or create.
                           Examples: "AWS Cloud Practitioner"
                                   "Learning::AWS Cloud Practitioner"

        Returns:
            bool: True if deck exists or was created successfully

        Raises:
            Exception: If deck creation fails
        """
        try:
            # Get all deck names
            deck_names = self._invoke("deckNames")

            if deck_name in deck_names:
                return True

            # Create the deck if it doesn't exist
            # Anki will automatically create parent decks for hierarchical names
            self._invoke("createDeck", {"deck": deck_name})
            return True

        except Exception as e:
            raise Exception(f"Failed to get or create deck '{deck_name}': {str(e)}")

    def add_card(
        self,
        deck_name: str,
        question: str,
        answer: str,
        tags: Optional[List[str]] = None
    ) -> Optional[int]:
        """
        Add a new flashcard to Anki with deduplication.

        This method creates a new note in the specified deck with the given
        question and answer. It automatically adds a unique card_id tag for
        deduplication purposes.

        Deck names can contain spaces. Examples:
        - "AWS Cloud Practitioner"
        - "Learning::AWS Cloud Practitioner"

        Args:
            deck_name (str): Name of the deck to add the card to (spaces allowed)
            question (str): The front of the card (question)
            answer (str): The back of the card (answer)
            tags (List[str], optional): Additional tags to add to the card.
                                       Example: ["source:remarkable",
                                                "notebook:AWS_cloud_practitioner",
                                                "date:2026-03-06"]

        Returns:
            Optional[int]: The Anki note ID if the card was added successfully,
                          None if the card is a duplicate

        Raises:
            Exception: If the card creation fails for reasons other than duplication
        """
        # Check if card already exists
        if self.card_exists_in_anki(question):
            print(f"Card already exists in Anki (duplicate question detected)")
            return None

        # Ensure the deck exists
        self.get_or_create_deck(deck_name)

        # Generate card ID for deduplication
        card_id = self.generate_card_id(question)

        # Prepare tags list
        all_tags = tags.copy() if tags else []
        all_tags.append(f"card_id:{card_id}")

        # Prepare note data
        note = {
            "deckName": deck_name,
            "modelName": "Basic",  # Using the default Basic note type
            "fields": {
                "Front": question,
                "Back": answer
            },
            "tags": all_tags,
            "options": {
                "allowDuplicate": False
            }
        }

        try:
            # Add the note
            note_id = self._invoke("addNote", {"note": note})
            print(f"Successfully added card to Anki (note ID: {note_id})")
            return note_id

        except Exception as e:
            error_message = str(e).lower()

            # Check if the error is due to a duplicate
            if "duplicate" in error_message or "cannot create note" in error_message:
                print(f"Card already exists in Anki (duplicate detected by Anki)")
                return None

            # Re-raise if it's a different error
            raise Exception(f"Failed to add card to Anki: {str(e)}")


# Example usage
if __name__ == "__main__":
    # Initialize the client
    client = AnkiClient()

    # Example 1: Add a card to a deck with spaces in the name
    note_id = client.add_card(
        deck_name="AWS Cloud Practitioner",  # Deck names can have spaces
        question="What is Amazon S3?",
        answer="Amazon Simple Storage Service (S3) is an object storage service that offers scalability, data availability, security, and performance.",
        tags=[
            "source:remarkable",
            "notebook:AWS_cloud_practitioner",
            "date:2026-03-06"
        ]
    )

    if note_id:
        print(f"Card added successfully with ID: {note_id}")
    else:
        print("Card was not added (duplicate)")

    # Example 2: Add a card to a hierarchical deck
    note_id2 = client.add_card(
        deck_name="Learning::AWS Cloud Practitioner",  # Hierarchical deck
        question="What is Amazon EC2?",
        answer="Amazon Elastic Compute Cloud (EC2) is a web service that provides resizable compute capacity in the cloud.",
        tags=[
            "source:remarkable",
            "notebook:AWS_cloud_practitioner",
            "date:2026-03-06"
        ]
    )
